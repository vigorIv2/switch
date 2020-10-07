#!/bin/bash
if curl -s https://nordvpn.com/  | grep Protected > /dev/null ; then
	echo "protected"
else
	echo "unprotected"
fi
	
