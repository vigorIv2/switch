#!/bin/bash
curl -i -H "Content-Type: application/json" -u toggle:relay -k -X POST -d '{"cid":"2","state":"0"}' http://192.168.7.180:8000/switch/api/v1.0/switch
sleep 5s
curl -i -H "Content-Type: application/json" -u toggle:relay -k -X POST -d '{"cid":"2","state":"1"}' http://192.168.7.180:8000/switch/api/v1.0/switch
sleep 3s
curl -i -H "Content-Type: application/json" -u toggle:relay -k -X POST -d '{"cid":"2","state":"1"}' http://192.168.7.180:8000/switch/api/v1.0/power

