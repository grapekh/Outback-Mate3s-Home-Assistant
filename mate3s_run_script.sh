#!/bin/bash
#
# Script Name:
#  /usr/local/bin/mate3s_run_script.sh
#
# Revision History: 
#  20201001 - Howie Grapek - Original 
#
# Description: 
#
#   Call the outback_mqtt_to_hassio.py script a bunch of times. 
#   this can be used as a simple stress test, or to 
#   Make this run as a stupid daemon - 
#   just set up the number of times to run and call the script. 
#
#   You can run this standalone if you want... OR, to deamonize it, put it in cron 
#
#   Here is timing... 
#   The script restarts if there are exceptions, and connects at BEST
#   every 15 seconds - then, it has a 4 second sleep in the script to publish topics. 
#   Just to be safe, run 2 times per minute. 
# 
#   So, lets set the script up to run: 
#   2 times in total before exiting
#   and call from cron every minute. 
#
# From cron, we write the output into a log file so we can check the activity if needed. 
#
# Cron Entry: 
# Min (0-50), Hour (0-23), Day of M (1-31),  Month of Y (1-12), Day of Week (0-7), Command
# * * * * * sh /usr/local/bin/mate3s_run_script.sh >> /var/log/mate3s_run_script.log 2>&1 &
#
# Note: 
# touch /var/log/mate3s_run_script.log as root
# and change the permissions to 666 so it can be written to from the cron daemon
# sudo touch /var/log/mate3s_run_script.log 
# sudo chmod 666 /var/log/mate3s_run_script.log
#
# Let it rip from Cron. 
#

NUM_RUNTIMES=2
# If this is 2, then it will run forever as a daemon

COUNTER=1
while [ $COUNTER -lt $NUM_RUNTIMES ]; do
  echo ""
  echo "Run number $COUNTER of $NUM_RUNTIMES iterations..."
  date;
  /usr/local/bin/outback_mqtt_to_hassio.py 
  #let COUNTER=COUNTER+1
  echo "**************************************************************"
done
