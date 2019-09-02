#!flask/bin/python

from flask import Flask, jsonify, abort, request, make_response, url_for, Response
import time
from flask_httpauth import HTTPBasicAuth
import datetime
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

temper_mva=[0.0,0]
temper_last=0.0
cpu_mva=[0.0,0]
cpu_last=0.0

def update_mva(ma,newv):
    nv=(ma[0]*ma[1]+newv)/(ma[1]+1)
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
    temperTemp=res[0].decode('utf-8').split("\n")[1].strip().split(" ")[2][0:-2].strip()
#    print("temperTemp="+temperTemp+"<")
    return float(temperTemp)

class MovingAverageThread (threading.Thread):
    def run (self):
        global temper_last
        global cpu_last
        while True:
            temper_last=get_temper_temp()
            update_mva(temper_mva,temper_last)
            cpu_last=get_cpu_temp()
            update_mva(cpu_mva,cpu_last)
            logconsole.info("Thread temper temper_last="+str(temper_last)+" mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
            logconsole.info("Thread cpu cpu_temp="+str(cpu_last)+" mva="+str(cpu_mva[0])+" cnt="+str(cpu_mva[1]))
            time.sleep(5)
        logconsole.info("Thread %s: finishing", name)

#mva = MovingAverageThread()
#mva.daemon = True
#mva.start()

def thread_function(name):
    logconsole.info("Thread %s: starting", name)
    while True:
        temper_temp=get_temper_temp()
        update_mva(temper_mva,temper_temp)
        cpu_temp=get_cpu_temp()
        update_mva(cpu_mva,cpu_temp)
        logconsole.info("Thread temper mva="+str(temper_mva[0])+" cnt="+str(temper_mva[1]))
        logconsole.info("Thread cpu mva="+str(cpu_mva[0])+" cnt="+str(cpu_mva[1]))
        time.sleep(5)
    logconsole.info("Thread %s: finishing", name)

# start temperature monitoring thread
#x = threading.Thread(target=thread_function, args=(1,))
#threads.append(x)
#x.start()

gpio_channels=[17,18,27,22]
gpio_state=[0,0,0,0] # must have same number of elements and all 0

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    for channel in gpio_channels:
        GPIO.setup(channel, GPIO.OUT)
        logconsole.info("GPIO channel "+str(channel)+" initialized")

def turn_on(channel_num):
    GPIO.output(gpio_channels[channel_num], GPIO.LOW)
    logconsole.info("GPIO channel "+str(channel_num)+"/"+str(gpio_channels[channel_num])+" state = LOW, aka ON")
    gpio_state[channel_num]=1

def turn_off(channel_num):
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

@auth.get_password
def get_password(username):
    if username == 'toggle':
        return 'relay'
    return None

setup_gpio()
all_on()

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

mva = MovingAverageThread()
mva.daemon = True
mva.start()

if __name__ == '__main__':
#    app.run(debug = True)
    app.run(host="0.0.0.0",threaded=True)

#    mva = MovingAverageThread()
#    mva.daemon = True
#    mva.start()

#    app.run(host="0.0.0.0")
