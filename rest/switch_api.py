#!flask/bin/python

from flask import Flask, jsonify, abort, request, make_response, url_for, Response
import time
from flask_httpauth import HTTPBasicAuth
import datetime
import RPi.GPIO as GPIO

import logging, logging.config, yaml
logging.config.dictConfig(yaml.load(open('logging.conf')))
logfl    = logging.getLogger('file')
logconsole = logging.getLogger('console')
logfl.debug("Debug FILE")
logconsole.debug("Debug CONSOLE")

app = Flask(__name__, static_url_path = "")
auth = HTTPBasicAuth()


gpio_channels=[17,18,27,22]
gpio_state=[0,0,0,0,0] # must have same number of elements and all 0

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
    for channel_num in range(0,len(gpio_channels)-1):
        turn_on(channel_num)

def all_off():
    for channel_num in range(0,len(gpio_channels)-1):
        turn_off(channel_num)

def shutdown_gpio():
    GPIO.cleanup()

@auth.get_password
def get_password(username):
    if username == 'toggle':
        return 'relay'
    return None

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
#    if request.json['cid'] < 0 or request.json['cid'] >= len(gpio_channels):
#        abort(400)
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

if __name__ == '__main__':
#    app.run(debug = True)
    setup_gpio()
    all_on()
    app.run(host="0.0.0.0")
