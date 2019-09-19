#!flask/bin/python

import os
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


gpio_channels=[17,18,27,22]
gpio_state=[0,0,0,0] # must have same number of elements and all 0

threshold=[[39,0],[39,0],[39,0],[39,0]]

temper_mva=[0.0,0]
temper_last=0.0
cpu_mva=[0.0,0]
cpu_last=0.0
stats_fn="temperature_stats.csv" 

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    for channel in gpio_channels:
        GPIO.setup(channel, GPIO.OUT)
        logconsole.info("GPIO channel "+str(channel)+" initialized")

def turn_on(channel_num,dry_run=False):
    if not dry_run:
        GPIO.output(gpio_channels[channel_num], GPIO.LOW)
    logconsole.info("GPIO channel "+str(channel_num)+"/"+str(gpio_channels[channel_num])+" state = LOW, aka ON")
    gpio_state[channel_num]=1

def turn_off(channel_num,dry_run=False):
    if not dry_run:
        GPIO.output(gpio_channels[channel_num], GPIO.HIGH)
    logconsole.info("GPIO channel "+str(channel_num)+"/"+str(gpio_channels[channel_num])+" state = HIGH, aka OFF")
    gpio_state[channel_num]=0

def all_on():
    for channel_num in range(0,len(gpio_channels)):
        turn_on(channel_num)

def all_off():
    for channel_num in range(0,len(gpio_channels)):
        turn_off(channel_num)

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

last_flip = 0

def ft(n):
    return "{:.2f}".format(n).strip("0").strip(".")

def root_dir():  # pragma: no cover
    return os.path.abspath(os.path.dirname(__file__))

def compact_report():
    global stats_fn
    date_days_ago = datetime.now() - timedelta(days=3)
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
    dts=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    csv.write("%s,%s,%s,%s,%s,%s,%s,%s,%s\n" % (dts,ft(temper_last),ft(temper_mva[0]),ft(cpu_last),ft(cpu_mva[0]),
        str(gpio_state[0]),str(gpio_state[1]),str(gpio_state[2]),str(gpio_state[3])))
    csv.close()
    logconsole.info("Checking now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
    logconsole.info("Checking cpu cpu_temp="+str(cpu_last)+" mva="+str(cpu_mva[0])+" cnt="+str(cpu_mva[1]))
    if now - last_flip > 180: # not too often, every 3 minute
        last_flip = now
        for cn in range(0,len(gpio_channels)):
            if threshold[cn][0] < temper_mva[0]: # turn it off
                if 0==gpio_state[cn]:
                    logconsole.info("The channel was already OFF now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
                else:
                    logconsole.info("Turn it OFF now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
                    turn_off(cn)
            else:    
                if 1==gpio_state[cn]:
                    logconsole.info("The channel was already ON now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
                else:
                    logconsole.info("Turn it ON now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
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
all_on()

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
	borderWidth: 2
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
	borderWidth: 2
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
	borderWidth: 2
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

@app.route('/', methods=['GET'])
def rootpage():  # pragma: no cover
    content = get_file('chart.html')
    return Response(content, mimetype="text/html")

@app.route('/js/<path:path>')
def send_js(path):
        return send_from_directory('js', path)

@app.route('/img/<path:path>')
def send_img(path):
        return send_from_directory('img', path)

@app.route('/font/<path:path>')
def send_font(path):
        return send_from_directory('font', path)

@app.route('/css/<path:path>')
def send_css(path):
        return send_from_directory('css', path)

@app.route('/scss/<path:path>')
def send_scss(path):
        return send_from_directory('scss', path)

mva = MovingAverageThread()
mva.daemon = True
mva.start()

if __name__ == '__main__':
    app.run(host="0.0.0.0",threaded=True)

