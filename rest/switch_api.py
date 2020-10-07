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

#gpio_channels_lp=[26,19,13,6]
gpio_channels_lp=[17,18,27,22]
gpio_state_lp_initial=[0,0,0,0] # some channels come back up powered on
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
        gpio_state_lp[cn] = gpio_state_lp_initial[cn]
        gpio_state[cn] = gpio_state_initial[cn]
        logconsole.info("GPIO channel "+str(gpio_channels[cn])+" initialized")

def push_power_button(cn,sleep_sec):
    # now let's push powerbutton on rig
    GPIO.setup(gpio_channels_lp[cn], GPIO.OUT)
    GPIO.output(gpio_channels_lp[cn], GPIO.LOW)
    logconsole.info("GPIO LP channel "+str(cn)+"/"+str(gpio_channels_lp[cn])+" state LOW")
    time.sleep(sleep_sec)
    GPIO.output(gpio_channels_lp[cn], GPIO.HIGH)
    logconsole.info("GPIO LP channel "+str(cn)+"/"+str(gpio_channels_lp[cn])+" state HIGH")
    GPIO.cleanup(gpio_channels_lp[cn])

def turn_off(cn):
    logconsole.info("GPIO channel "+str(cn)+"/"+str(gpio_channels[cn])+" state = LOW, aka OFF")
    GPIO.output(gpio_channels[cn], GPIO.LOW)
    gpio_state[cn]=1

def turn_on_lp(cn):
    push_power_button(cn,0.65)
    gpio_state_lp[cn] = 1

def turn_on(cn):
    GPIO.output(gpio_channels[cn], GPIO.HIGH)
    gpio_state[cn]=0
    logconsole.info("GPIO channel "+str(cn)+"/"+str(gpio_channels[cn])+" state = HIGH, aka ON")

def turn_off_lp(cn):
    push_power_button(cn,0.65)
    gpio_state_lp[cn] = 0

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

def run_shell_cmd(cmd):
    output = Popen(cmd,stdout=PIPE,stderr=PIPE)
    response = output.communicate()
    rc = output.returncode
    return response, rc

def removeObsoleteSshKey(raddr):
    res, rc = run_shell_cmd(["ssh-keygen","-R",raddr])

def set_remote_time(cn):
    raddr = getRigAddress(cn)
    if raddr != "":
        removeObsoleteSshKey(raddr)
        now_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rc = os.WEXITSTATUS(os.system('ssh -o "StrictHostKeyChecking=no" -i /home/pi/.ssh/nhos_rsa nhos@' + raddr + " \'sudo date -s \""+str(now_time)+"\"\' 2>&1"))
        logconsole.info("setting date "+str(now_time)+" on host "+raddr+" for channel "+str(cn)+" rc="+str(rc))
        return rc
    return 0

def get_remote_time(cn):
    raddr = getRigAddress(cn)
    if raddr != "":
        removeObsoleteSshKey(raddr)
        res, rc = run_shell_cmd(["ssh", "-o", "StrictHostKeyChecking=no", "-i", "/home/pi/.ssh/nhos_rsa", "nhos@" + raddr, "date", "+\"%Y-%m-%d %H:%M:%S\""])
        logconsole.info("getting remote date for "+raddr+" channel "+str(cn)+" response " +str(res[0].strip())+" rc="+str(rc))
        return res, rc
    return "", 1

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

def writeState(cn,state):
    cn_state_file = open("cn_"+str(cn)+".state", "w")
    n = cn_state_file.write(state)
    cn_state_file.close()
 
def getRigAddress(cn):
    rigs=getRigsConfig()["rigs"]
    res=""
    if len(rigs) > cn: 
        r=rigs[cn]
        if "address" in r and not r["address"] is None: 
            res=r["address"]
    return res

def getRigStatus(cn):
    rigs=getRigsConfig()["rigs"]
    res=False
    if len(rigs) > cn: 
        r=rigs[cn]
        res=False
        if "ID" in r and not r["ID"] is None: 
            rid=r["ID"]
            status=run_cmd([root_path+"/switch/rest/api_check.sh",rid])
            try:
                res = status[0].strip() in ['"GREEN"']
                writeState(cn,status[0])
            except:
                res = False
            logconsole.info("Rig Status cn="+str(cn)+"; rid="+str(rid)+"; name="+r["name"]+"; up="+str(res)+"; status="+str(status))
    else:
        res=True # for rigs not in config file report fake True, to not flip relays fruitlessly
        writeState(cn,'"N/A"\n')
    return res

def ft(n):
    return "{:.2f}".format(n).strip("0").strip(".")

def root_dir():  # pragma: no cover
    return os.path.abspath(os.path.dirname(__file__))

def compact_report():
    global stats_fn
    date_days_ago = datetime.now() - timedelta(days=getRigsConfig()["report_days"])
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

def track_temperature():
    global temper_last
    global cpu_last
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
    diff_mva=cpu_mva[0]-temper_mva[0]
    logconsole.info("Tracking temperature now="+str(now)+" temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1])+" cpu_temp="+str(cpu_last)+" cpu_mva="+str(cpu_mva[0])+" diff_mva="+str(diff_mva))

class MovingAverageThread(threading.Thread):
    def run (self):
        logconsole.info("Temperature tracking thread started")
        while True:
            track_temperature()
            res=run_cmd(["./protected.sh"])
            pr_file = open("protected.net", "w")
            pr_file.write(res[0].strip())
            pr_file.close()
            time.sleep(120)
            
def powercycle(cn):
    logconsole.info("Begin powercycle cn "+str(cn))
    power_off(cn)
    power_on(cn)
    time.sleep(150)
    set_remote_time(cn)

    logconsole.info("End powercycle cn "+str(cn))

def power_off(cn):
    logconsole.info("Begin power_off cn "+str(cn))
    turn_off_lp(cn)
    time.sleep(7)
    turn_off(cn)
    time.sleep(17)
    writeState(cn,"\"RED\"\n")
    logconsole.info("End power_off cn "+str(cn))

def power_on(cn):
    logconsole.info("Begin power_on cn "+str(cn))
    turn_on(cn)
    time.sleep(3)
    turn_on_lp(cn)
    logconsole.info("End power_on cn "+str(cn))

def watch_channel(cn):
    logconsole.info("Watch channel %s", cn) 
    if threshold[cn][0] < temper_mva[0]: # turn it off, it is too hot
        rd, rc = get_remote_time(cn)
        if rc != 0:
            logconsole.info("Channel "+str(cn)+" is too hot, and is already off")
            return
        power_off(cn)
        return

    rd, rc = get_remote_time(cn)
    if rc != 0: # ssh failed, reboot it, or turn it on
        powercycle(cn)
        time.sleep(180)

    attempt=0
    while not getRigStatus(cn): # status not green, keep checking for a while
        logconsole.info("Awaiting Channel "+str(cn)+ " attempt "+str(attempt)+"; status update status=False")
        set_remote_time(cn)
        time.sleep(180)
        attempt += 1
        if attempt > 9:
            logconsole.info("Too many attempts, rebooting cn="+str(cn))
            powercycle(cn)
            return
    logconsole.info("Channel "+str(cn)+" looking good, Status=True")

class ChannelWatchdogThread(threading.Thread):
    def __init__(self, number):
        super(ChannelWatchdogThread, self).__init__()
        self.channel_number = number
    def run (self):
        cn=self.channel_number
        logconsole.info("Watchdog thread for channel %s: started", cn)
        track_temperature() # to populate temper_mva
        if threshold[cn][0] >= temper_mva[0]: # turn it off, it is too hot
            logconsole.info("Initial turn on for channel %s", cn)
            power_on(cn)
            time.sleep(180)
            set_remote_time(cn)
        while True:
            watch_channel(cn)
            time.sleep(70)

@auth.get_password
def get_password(username):
    if username == 'toggle':
        return 'relay'
    return None

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

@app.route('/switch/api/v1.0/protected', methods=['GET'])
def protected():  # draw an HTML element indicating status of connection
    res=run_cmd(["cat","./protected.net"])
    res=res[0].strip()
    color="red"
    if res == "protected" :
        color="black"
    element="<font size=90px color="+color+"><h1>"+res+"</h1></font>"
    return Response(element, mimetype="text/html")

@app.route('/switch/api/v1.0/bulb/<cn>', methods=['GET'])
def bulb(cn):  # draw an HTML element indicating given channel status
    try:
        statefn = os.path.join(root_dir(), "cn_"+cn+".state")
        state = open(statefn).read().strip()
    except IOError as exc:
        state='"PURPLE"'
    logconsole.info("bulb executed cn="+str(cn)+" color="+state)
    element="<font size=50px color="+state+">&#x25CF;</font>"
    return Response(element, mimetype="text/html")

@auth.error_handler
def unauthorized():
#    return make_response(jsonify( { 'error': 'Unauthorized access' } ), 403)
    return make_response(jsonify( { 'error': 'Unauthorized access' } ), 401)
    # return 403 instead of 401 to prevent browsers from displaying the default auth dialog
    
@app.errorhandler(400)
def not_found_400(error):
    return make_response(jsonify( { 'error': 'Bad request' } ), 400)

@app.errorhandler(404)
def not_found_404(error):
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
    state = request.json['state']
    if "flip" == state:
        if getRigStatus(cid):
          logconsole.info("current status=Up")
          state="0"
        else:  
          logconsole.info("current status=Down")
          state="1"

    if "0" == state:
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
    state = request.json['state']
    if "flip" == state:
        if getRigStatus(cid):
          logconsole.info("current status=Up")
          state="0"
        else:  
          logconsole.info("current status=Down")
          state="1"

    if "0" == state:
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

setup_gpio()

mva = MovingAverageThread()
mva.daemon = True
thread_list = []
thread_list.append(mva)
mva.start()
rigs=getRigsConfig()["rigs"]
for rig in rigs:
    cn = int(rig["channel"])
    watchdog_thread = ChannelWatchdogThread(cn)
    watchdog_thread.daemon = True
    thread_list.append(watchdog_thread)
    watchdog_thread.start()
    time.sleep(5)

if __name__ == '__main__':
    app.run(host="0.0.0.0",threaded=True)