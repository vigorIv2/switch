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
SECRET=`jq '.["secret"]' .api_creds.json | sed 's/"//g'`

export report=`python ${COMMAND} -b ${URL} -o ${ORG} -k ${KEY} -s ${SECRET} -m GET -p ${URI} | jq ".groups.\"\".rigs[] | select(.rigId == \"${ID}\")" | jq ".status" 2>&1 `
STATES=`jq -r '.["state"] | values' .api_creds.json | sed '/^{/d' | sed '/^}/d' | sed 's/^ *//' | sed 's/\,$//'` 
while IFS=: read -r k v; do
	report=`echo $report | sed "s/$k/$v/"`
done <<< "$(echo -e "$STATES")"
echo $report
