#!/bin/bash

if [ "x$1" == "x" ]; then
	echo "Uaage: api_check.sh <id>"
	exit 1
fi      	
ID=$1
COMMAND=`jq '.["cmd"]' .api_creds.json | sed 's/"//g'`
URL=`jq '.["url"]' .api_creds.json | sed 's/"//g'`
URI=`jq '.["uri"]' .api_creds.json | sed 's/"//g'`
ORG=`jq '.["org"]' .api_creds.json | sed 's/"//g'`
KEY=`jq '.["key"]' .api_creds.json | sed 's/"//g'`
OK_STATUS=`jq '.["OK_STATUS"]' .api_creds.json`
SECRET=`jq '.["secret"]' .api_creds.json | sed 's/"//g'`

python ${COMMAND} -b ${URL} -o ${ORG} -k ${KEY} -s ${SECRET} -m GET -p ${URI} | jq ".groups.\"\".rigs[] | select(.rigId == \"${ID}\")" | jq ".status" | sed "s/${OK_STATUS}/OK/"
