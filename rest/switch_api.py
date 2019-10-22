#!flask/bin/python

import os
import json
from flask import Flask, jsonify, abort, request, make_response, url_for, Response, send_from_directory
import time
from datetime import datetime, timedelta
from flask_httpauth import HTTPBasicAuth
import threading
import RPi.GPIO as GPIO
from subprocess import Popen, PIPE

import logging, logging.config, yaml
logging.config.dictConfig(yaml.load(open('logging.conf')))
logfl    = logging.getLogger('file')
logconsole = logging.getLogger('console')
logfl.debug("Debug FILE")
logconsole.debug("Debug CONSOLE")

app = Flask(__name__, static_url_path = "")
auth = HTTPBasicAuth()

root_path="/home/pi"
rigs_fn = ".rigs.json"

#reboot_time=[["01:00", "03:00", "06:00", "09:00", "12:00", "14:00", "17:00", "19:00", "21:00"],
#             ["01:10", "03:10", "06:10", "09:10", "12:10", "14:10", "17:10", "19:10", "21:00"],
#             ["01:20", "03:20", "06:20", "09:20", "12:20", "14:20", "17:20", "19:20", "21:20"],
#             ["01:30", "03:30", "06:30", "09:30", "12:30", "14:30", "17:30", "19:30", "21:30"]]
             
#gpio_channels_lp=[26,19,13,6]
gpio_channels_lp=[17,18,27,22]
gpio_state_lp_initial=[0,1,1,1] # some channels come back up powered on
gpio_state_lp=[0,0,0,0] # must have same number of elemens

#gpio_channels=[17,18,27,22]
gpio_channels=[26,19,13,6]
gpio_state_initial=[0,0,0,0] # all hight power channels come back powered off
gpio_state=[0,0,0,0] # must have same number of elements and all 0

temp_too_high=40
threshold=[[temp_too_high+0.1,0],[temp_too_high+0.2,0],[temp_too_high+0.3,0],[temp_too_high+0.4,0]]

temper_mva=[0.0,0]
temper_last=0.0
cpu_mva=[0.0,0]
cpu_last=0.0
stats_fn="temperature_stats.csv" 

def getRigsConfig():
    rigs={}
    with open(rigs_fn) as json_file:
        rigs = json.load(json_file)
    return rigs

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    for cn in range(0,len(gpio_channels)):
        GPIO.setup(gpio_channels[cn], GPIO.OUT)
        logconsole.info("GPIO channel "+str(gpio_channels[cn])+" initialized")

def push_power_button(cn,sleep_sec):
    # now let's push powerbutton on rig
    GPIO.setup(gpio_channels_lp[cn], GPIO.OUT)
    logconsole.debug("GPIO channel lp "+str(gpio_channels_lp[cn])+" initialized")
    GPIO.output(gpio_channels_lp[cn], GPIO.LOW)
    logconsole.info("GPIO LP channel "+str(cn)+"/"+str(gpio_channels_lp[cn])+" state LOW")
    time.sleep(sleep_sec)
    GPIO.output(gpio_channels_lp[cn], GPIO.HIGH)
    logconsole.info("GPIO LP channel "+str(cn)+"/"+str(gpio_channels_lp[cn])+" state HIGH")
    GPIO.cleanup(gpio_channels_lp[cn])
    logconsole.debug("GPIO LP channel "+str(cn)+"/"+str(gpio_channels_lp[cn])+" clean")

def turn_on(cn):
    logconsole.info("GPIO channel "+str(cn)+"/"+str(gpio_channels[cn])+" state = LOW, aka ON")
    GPIO.output(gpio_channels[cn], GPIO.LOW)
    gpio_state[cn]=1

def turn_on_lp(cn):
    push_power_button(cn,0.65)
    gpio_state_lp[cn] = 1

def turn_off(cn):
    GPIO.output(gpio_channels[cn], GPIO.HIGH)
    gpio_state[cn]=0
    logconsole.info("GPIO channel "+str(cn)+"/"+str(gpio_channels[cn])+" state = HIGH, aka OFF")

def turn_off_lp(cn):
    push_power_button(cn,0.65)
    gpio_state_lp[cn] = 0

def all_on():
    for cn in range(0,len(gpio_channels)):
        turn_on(cn)

def all_off():
    for cn in range(0,len(gpio_channels)):
        turn_off(cn)

def shutdown_gpio():
    GPIO.cleanup()

def update_mva(ma,newv):
    cnt=ma[1]
    if cnt > 10:
        cnt=10
    nv=(ma[0]*cnt+newv)/(cnt+1)
    ma[1]+=1
    ma[0]=nv

def run_cmd(cmd):
    output = Popen(cmd,stdout=PIPE)
    response = output.communicate()
    return response

def get_cpu_temp():
    res=run_cmd(["cat","/sys/class/thermal/thermal_zone0/temp"])
    cpuTemp0=int(res[0].strip())
    cpuTemp1=cpuTemp0/1000
    cpuTemp2=cpuTemp0/100
    cpuTempM=cpuTemp2 % cpuTemp1
    return float(str(cpuTemp1)+"."+str(cpuTempM))

def get_gpu_temp():
    res=run_cmd(["/opt/vc/bin/vcgencmd","measure_temp)"])
    gpuTemp=res[0] #.strip().replace("temp=", "").replace("'C","")
    return gpuTemp

def get_temper_temp():
    res=run_cmd(["/usr/local/bin/temper-poll"])
    temperTemp=0
    try:
        temperTemp=res[0].decode('utf-8').split("\n")[1].strip().split(" ")[2][0:-2].strip()
    except:
        logconsole.info("get_temper_temp exception "+str(res))
        temperTemp=38.888
    return float(temperTemp)

def getRigStatus(cn):
    r=getRigsConfig()["rigs"][cn]
    res=False
    if "ID" in r and not r["ID"] is None: 
        rid=r["ID"]
        res=run_cmd([root_path+"/switch/rest/api_check.sh",rid])
        try:
            res="OK" == res[0].strip()
        except:
            res = False
    logconsole.info("Rig Status rid="+str(rid)+" up="+str(res))
    return res

last_flip = 0

def ft(n):
    return "{:.2f}".format(n).strip("0").strip(".")

def root_dir():  # pragma: no cover
    return os.path.abspath(os.path.dirname(__file__))

def compact_report():
    global stats_fn
    date_days_ago = datetime.now() - timedelta(days=7)
    dts_days_ago=date_days_ago.strftime("%Y-%m-%d")
    csvn = open("new_%s" % (stats_fn), "a+")
    with open(stats_fn) as fp:
       line = fp.readline()
       while line:
          dl = line.split(" ")[0] # just date
          if dl >= dts_days_ago:
             csvn.write(line)
          line = fp.readline()
    csvn.close()      
    os.rename("new_%s" % (stats_fn), stats_fn) 

logconsole.info("------------------------------ Starting temperature monitoring service ========================================")
compact_report()

def check_temperature():
    global temper_last
    global cpu_last
    global last_flip
    global stats_fn
    temper_last=get_temper_temp()
    update_mva(temper_mva,temper_last)
    cpu_last=get_cpu_temp()
    update_mva(cpu_mva,cpu_last)
    now = time.time() 
    csv = open(stats_fn, "a+")
    ctme=datetime.now().strftime("%H:%M")

    dts=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    csv.write("%s,%s,%s,%s,%s,%s,%s,%s,%s\n" % (dts,ft(temper_last),ft(temper_mva[0]),ft(cpu_last),ft(cpu_mva[0]),
        str(gpio_state[0]),str(gpio_state[1]),str(gpio_state[2]),str(gpio_state[3])))
    csv.close()
    logconsole.debug("Checking now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1])+" cpu_temp="+str(cpu_last)+" cpu_mva="+str(cpu_mva[0]))
    if now - last_flip > 120: # not too often, every 2 minute
        last_flip = now
        for cn in range(0,len(gpio_channels)):
            getRigStatus(cn)
            if threshold[cn][0] < temper_mva[0]: # turn it off
                if 0==gpio_state[cn]:
                    logconsole.info("The channel "+str(cn)+" was already OFF now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
                else:
                    logconsole.info("Turn channel "+str(cn)+" OFF now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
                    turn_off_lp(cn)
                    time.sleep(4)
                    turn_off(cn)
                continue    
            else:    
                if 1==gpio_state[cn]:
                    logconsole.info("The channel "+str(cn)+" was already ON now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
                    if 0==gpio_state_lp[cn]:
                        turn_on_lp(cn)
                    else:
                        logconsole.info("The LP channel "+str(cn)+" was already ON now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
                else:
                    logconsole.info("Turn channel "+str(cn)+" ON now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
                    turn_on(cn)

            time.sleep(2) # not all 4 lines at the same time    

class MovingAverageThread(threading.Thread):
    def run (self):
        while True:
            check_temperature()
            time.sleep(10)
        logconsole.info("Thread %s: finishing", name)

@auth.get_password
def get_password(username):
    if username == 'toggle':
        return 'relay'
    return None

setup_gpio()

def get_file(filename):  # pragma: no cover
    try:
        src = os.path.join(root_dir(), filename)
        return open(src).read()
    except IOError as exc:
        return str(exc)

@app.route('/switch/api/v1.0/stats', methods=['GET'])
def stats():  
    global stats_fn
    content = get_file(stats_fn)
    return Response(content, mimetype="text/csv")

@app.route('/switch/api/v1.0/chart', methods=['GET'])
def chart():  # pragma: no cover
    global stats_fn
    content = get_file(stats_fn)

    tempertemps=[]
    lables=[]
    tempergpu=[]
    th=[]
    tm=""
    for l in content.split("\n"):
        if l == "":
            break
        c = l.split(",")
        ctm=c[0][5:13]
        if ctm != tm:
            tm=ctm
            lables.append(ctm)
            tempertemps.append(c[1])
            tempergpu.append(c[3])
            th.append(threshold[0][0])
            
    lablesstr=', '.join("\"{0}\"".format(w) for w in lables)
    chart1=', '.join("{0}".format(w) for w in tempertemps)
    chart2=', '.join("{0}".format(w) for w in tempergpu)
    chart3=', '.join("{0}".format(w) for w in th)
    body="""
var ctxL = document.getElementById("lineChart").getContext('2d');
var myLineChart = new Chart(ctxL, {
  type: 'line',
  data: {
    labels: ["""+lablesstr+"""],
    datasets: [{
	label: "Sensor",
	data: ["""+chart1+"""],
	backgroundColor: [
	  'rgba(105, 0, 132, .2)',
	],
	borderColor: [
	  'rgba(200, 99, 132, .7)',
	],
	borderWidth: 1
      },
      {
	label: "CPU",
	data: ["""+chart2+"""],
	backgroundColor: [
	  'rgba(0, 137, 132, .2)',
	],
	borderColor: [
	  'rgba(0, 10, 130, .7)',
	],
	borderWidth: 1
      },
       {
	label: "Threshold",
	data: ["""+chart3+"""],
	backgroundColor: [
	  'rgba(30, 127, 172, .2)',
	],
	borderColor: [
	  'rgba(40, 13, 140, .7)',
	],
	borderWidth: 1
      }
    ]
  },
  options: {
    responsive: true
  }
});
"""
    return Response(body, mimetype="text/javascript")


@auth.error_handler
def unauthorized():
#    return make_response(jsonify( { 'error': 'Unauthorized access' } ), 403)
    return make_response(jsonify( { 'error': 'Unauthorized access' } ), 401)
    # return 403 instead of 401 to prevent browsers from displaying the default auth dialog
    
@app.errorhandler(400)
def not_found(error):
    return make_response(jsonify( { 'error': 'Bad request' } ), 400)

@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify( { 'error': 'Not found' } ), 404)

def make_public_state(state):
    new_state = {}
    for field in state:
            new_state[field] = state[field]
    return new_state

def make_public_switch(switch):
    new_switch = {}
    for field in switch:
            new_switch[field] = switch[field]
    return new_switch

@app.route('/switch/api/v1.0/switch', methods = ['POST'])
@auth.login_required
def get_switch():
    logconsole.info("get_switch called with "+str(request.json)+" len(gpio_channels)="+str(len(gpio_channels)))
    if not request.json or not 'cid' in request.json:
        abort(400)
    if int(request.json['cid']) < 0 or int(request.json['cid']) >= len(gpio_channels):
        abort(400)
    if not request.json or not 'state' in request.json:
        abort(400)
    switch = {
        'cid': request.json['cid'],
        'state': request.json['state'], 
    }

    cid = int(request.json['cid'])
    state = int(request.json['state'])
    if state == 0:
        turn_off(cid)
    else:
        turn_on(cid)

    return jsonify( { 'switch': make_public_switch(switch) } ), 201

@app.route('/switch/api/v1.0/power', methods = ['POST'])
@auth.login_required
def get_power():
    logconsole.info("get_power called with "+str(request.json)+" len(gpio_channels)="+str(len(gpio_channels)))
    if not request.json or not 'cid' in request.json:
        abort(400)
    if int(request.json['cid']) < 0 or int(request.json['cid']) >= len(gpio_channels):
        abort(400)
    if not request.json or not 'state' in request.json:
        abort(400)
    switch = {
        'cid': request.json['cid'],
        'state': request.json['state'], 
    }

    cid = int(request.json['cid'])
    state = int(request.json['state'])
    if state == 0:
        turn_off_lp(cid)
    else:
        turn_on_lp(cid)

    return jsonify( { 'switch': make_public_switch(switch) } ), 201

@app.route('/switch/api/v1.0/state', methods = ['POST'])
@auth.login_required
def get_state():
    global temper_last
    global cpu_last
    logconsole.info("get_state called with "+str(request.json))
    state = {
        'state'      : gpio_state,
        'temper'     : str(temper_last),
        'cpu'        : str(cpu_last),
        'temper_mva' : str(temper_mva[0]),
        'cpu_mva'    : str(cpu_mva[0])
    }

    return jsonify( { 'state': make_public_state(state) } ), 201

mva = MovingAverageThread()
mva.daemon = True
mva.start()

if __name__ == '__main__':
    app.run(host="0.0.0.0",threaded=True)

