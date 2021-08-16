#!/usr/bin/python3
#  
# Copyright (C) 2020 Howie Grapek <howiegrapek@yahoo.com>
# All rights reserved. This program and the accompanying materials
# are made available under the terms of the GPL License v1.0
# which accompanies this distribution. 
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#  
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License at <http://www.gnu.org/licenses/>
# for more details.
# 
# CONTRIBUTORS: 
#    Howie Grapek - Totally mine. fun fun fun
#
# DESCRIPTION: 
#   This program imports data into mosquito, so homeassistant can read it 
#   This can be run from cron every minute or so to update the mqtt topics.  
#   Or, we can make it a daemon, but that sounds like way too muck work. 
#
#   Data is coming from outback Mate3s. 
# 
# HOW TO RUN AS A DAEMON:
#   Add to the crontab and run every minute like follows
#     m h  dom mon dow   command
#     * * * * * /usr/local/bin/outback_mqtt_to_hassio.py >> /var/log/mate3s.log &
#
# REVISION HISTORY:
#	V1.0 20200825 - Original - Designed / tested with Python 3.8
#	V1.1 20200915 - Added more MQTT Fields and sysinfo topic
#	V1.2 20201002 - Worked on file open time out issues. 
#		Handle exceptions for: 
#		  urllib.error.URLError: <urlopen error [Errno 60] Operation timed out>
#		  urllib.error.URLError: <urlopen error timed out>
#		  socket.timeout: timed out
#		  json.decoder.JSONDecodeError: Extra data: line 7 column 4 (char 715)
#
#		Sometimes get this for strange reasons: 
#		  json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 5 column 42 (char 141)
#
# 	V1.3 20201004 - Talk to hassio broker
#		Added system time in mate3s epoch and human readable time format. 
#
#       V1.4 20201009 - ADded Load calculations (in watts) and addition of another topic. 
#       V1.5 20201013 - Changed getmac to use ETH_INTERFACE variable because on the raspi, it was returning none from eth address. 
#	V1.6 20201015 - Mate3s port 80 sometimes goes offline - check and report if it fails.
#			Specifically check for these fatal errors: 
#				URLError caught after 10 seconds - because of this error:
#				<urlopen error [Errno 113] No route to host>
#				<urlopen error [Errno 111] Connection refused>
#	V1.6.1 20201016 - Don't send more than 10 alarms. If it clears, then reset counter. 
#	V1.6.2 20201017 - Added more content to alarm and cleaned up. 
#       V1.7.0 20201018 - Repaired num_port sanity check - and added variables
#       V1.7.1 20201020 - Added datestamp and banner to start. 
#       V1.7.2 20201217 - Updated IP Addresses for Nuc
#	V1.7.3 20210714 - added battery capacity and type as well as FM100 change. 
#
#
##################
#
# This is the json schema from the Mate 3. 
# It will look like this: 
# http://10.0.0.150/Dev_status.cgi?Port=0
#
#
# {"devstatus": {
#  "Gateway_Type": "Mate3s","Sys_Time": 1601464964,
#  "Sys_Batt_V": 53.9,
#  "ports": [
#{ "Port": 1,
#	"Dev": "FXR",
#	"Type": "60Hz",
#	"Inv_I_L2": 0,
#	"Chg_I_L2": 0,
#	"Buy_I_L2": 0,
#	"Sell_I_L2": 0,
#	"VAC1_in_L2": 0,
#	"VAC2_in_L2": 0,
#	"VAC_out_L2": 122,
#	"AC_Input": "Grid",
#	"Batt_V": 54.0,
#	"AC_mode": "NO AC",
#	"INV_mode": "Inverting",
#	"Warn": ["none"],
#	"Error": ["none"],
#	"AUX": "disabled"},
#	
#{ "Port": 2,
#	"Dev": "CC",
#	"Type": "FM100",
#	"Out_I": 1.4,
#	"In_I": 0,
#	"Batt_V": 54.4,
#	"In_V": 110.1,
#	"Out_kWh": 0.3,
#	"Out_AH": 6,
#	"CC_mode": "",
#	"Error": ["none"],
#	"Aux_mode": "Manual",
#	"AUX": "disabled"},
#	
#{ "Port": 3,
#	"Dev": "FNDC",
#	"Enabled": ["A",
#	"B"],
#	"Shunt_A_I": -0.9,
#	"Shunt_A_AH": -2,
#	"Shunt_A_kWh": -0.100,
#	"Shunt_B_I":  1.2,
#	"Shunt_B_AH": 2,
#	"Shunt_B_kWh":  0.120,
#	"SOC": 100,
#	"Min_SOC": 92,
#	"Days_since_full": 8.0,
#	"CHG_parms_met": false,
#	"In_AH_today": 21,
#	"Out_AH_today": 8,
#	"In_kWh_today":  1.150,
#	"Out_kWh_today":  0.390,
#	"Net_CFC_AH": 0,
#	"Net_CFC_kWh":  0.020,
#	"Batt_V": 53.9,
#	"Batt_temp": "###",
#	"Aux_mode": "manual",
#	"AUX": "disabled"}
#]}}

VERSION="V1.7.3"

import paho.mqtt.client as mqtt
import json
import requests
import time
import uuid
import netifaces
import getmac
import urllib.request
import sys
from json.decoder import JSONDecodeError
from urllib.error import HTTPError, URLError
import socket
import os

# Define Variables 

DEBUG1=True				# basic debug output - Set to True when developing otherwise False
DEBUG2=False				# more deep debug output - Set to True when developing otherwise False	
DEBUG3=False				# If this is true, we will perform pauses (interactive testing), otherwise, just go. 
ONGRID=False				# This is a flag to allow us to calculate power - if on grid. 

HTTP_TIMEOUT=20				# Number of seconds to the read to mate3s (normally takes around 10 seconds)
THRESHOLD = 5				# Number of retries of fatal errors
TMPFILE="/tmp/mqtt_error_count.txt"	# name of file to write counter data into (It stays persistant even if code crashes)

#MQTT_HOST = "localhost"		# This is my local machine
#MQTT_HOST = "10.1.10.6"		# Publish to Homeassistant (raspi). 
MQTT_HOST = "10.1.10.26"			# Publish to Homeassistant (nuc). 
ETH_INTERFACE="eth0"			# required for getmac

# Creds at my hassio mosquito broker. 
MQTT_USERNAME = "PUT_YOUR_MQTT_USERNAME_HERE"
MQTT_PASSWORD = "PUT_YOUR_MQTT_PASSWORD_HERE"

MQTT_PORT = 1883
MQTT_KEEPALIVE_INTERVAL = 45
MQTT_TOPIC = "Mate3s"
MQTT_QOS = 0
MQTT_RETAIN = True

#
# These are specific to the configuration you have
# Used for topic information to be published in mqtt 
#
MATE3S_INV_MODEL = "FXR3048"
MATE3S_CC_MODEL = "FM100"
MATE3S_BATTERY_TYPE = "KiloVault HAB 7.5"			
MATE3S_BATTERY_CAPACITY = "160"			
MATE3S_API_IP_ADDRESS = "10.1.10.150"

# Put your email address (and your text email address if desired here. 
# Example for numbers and email for public use only, replace with real info
EMAIL_RECIPIENTS = "PUT_YOUR_EMAIL_ADDRESS_HERE@DOMAIN.COM,1112223333@txt.att.net"

#
# IN OUR ENVIRONMENT, We expect 3 devices here...  
# Port 1: FXR Inverter
# Port 2: CC FM100
# Port 3: FNDC - FlexNet DC
#
# Set this variable now, so we can check down below in sanity checking. 
# 
NUM_PORTS = 3

# This is required to eliminate the default value and python error from the raw json data received. 
false = False;

#
# Example JSON Data to test with. 
#
MQTT_MSG=json.dumps( 
  {"devstatus": {
    "Gateway_Type": "Mate3s",
    "Sys_Time": 1601467711,
    "Sys_Batt_V": 54.0,
  "ports": [
{ "Port": 1,
	"Dev": "FXR",
	"Type": "60Hz",
	"Inv_I_L2": 0,
	"Chg_I_L2": 0,
	"Buy_I_L2": 0,
	"Sell_I_L2": 0,
	"VAC1_in_L2": 0,
	"VAC2_in_L2": 0,
	"VAC_out_L2": 122,
	"AC_Input": "Grid",
	"Batt_V": 54.0,
	"AC_mode": "NO AC",
	"INV_mode": "Inverting",
	"Warn": ["none"],
	"Error": ["none"],
	"AUX": "disabled"},
	
{ "Port": 2,
	"Dev": "CC",
	"Type": "Silent",
	"Out_I": 1.4,
	"In_I": 0,
	"Batt_V": 54.4,
	"In_V": 110.1,
	"Out_kWh": 0.3,
	"Out_AH": 6,
	"CC_mode": "",
	"Error": ["none"],
	"Aux_mode": "Manual",
	"AUX": "disabled"},
	
{ "Port": 3,
	"Dev": "FNDC",
	"Enabled": ["A",
	"B"],
	"Shunt_A_I": -0.9,
	"Shunt_A_AH": -2,
	"Shunt_A_kWh": -0.100,
	"Shunt_B_I":  1.2,
	"Shunt_B_AH": 2,
	"Shunt_B_kWh":  0.120,
	"SOC": 100,
	"Min_SOC": 92,
	"Days_since_full": 8.0,
	"CHG_parms_met": false,
	"In_AH_today": 21,
	"Out_AH_today": 8,
	"In_kWh_today":  1.150,
	"Out_kWh_today":  0.390,
	"Net_CFC_AH": 0,
	"Net_CFC_kWh":  0.020,
	"Batt_V": 53.9,
	"Batt_temp": "###",
	"Aux_mode": "manual",
	"AUX": "disabled"}
]}}

);
    

#########################################
# Clear Error Counter - File i/o
# This is how we would set the initial number
#########################################

def clear_counter_value():
  NUM = 0
  
  if DEBUG2 == True:
    print ("DEBUG: Writing ", NUM , " to: ", TMPFILE)

  f = open(TMPFILE,'w')
  f.write(str(NUM))
  f.close()


#########################################
# Read Error Counter - File i/o
# Deal with file does not exist also.
#########################################

def read_counter_value():

  if DEBUG2 == True:
    print ("DEBUG: Read error counter ... ")

  try: 
    f = open(TMPFILE, 'r')

  except IOError: 
    # File doesn't exist yet, so lets make believe we read "0"
    if DEBUG2 == True:
      print ("DEBUG: File does not exist.... no biggie. lets return default value of 0")
    ecount = int(0);
    return(ecount)

  ecount = int(f.read())
  f.close()

  if DEBUG2 == True:
    print ("DEBUG: Got ", ecount, " from the file")

  return (ecount)

#########################################
# Write a new number into the file.  i/o
# We should probably check to see if this fails, but we are writing into /tmp, 
# so, I'm just lazy.   If we cannot write to the /tmp directory, we 
# have bigger issues. 
#########################################

def write_counter_value(new_num):

  if DEBUG2 == True:
    print ("DEBUG: writing ", new_num, " to the file: ", TMPFILE, "... ")

  f = open(TMPFILE,'w')  			
  f.write(str(new_num))
  f.close()

#########################################
# Get the Json Data from the rest api... 
# http://10.0.0.150/Dev_status.cgi?Port=0
# MATE3S_API_IP_ADDRESS is the place. 
######################################### 

# What time is it? 
t = time.localtime()
current_time = time.strftime("%Y%m%d %H:%M:%S", t)

# Ok, lets start the system!!
print ("")
print ("*** Mate3s to MQTT - Version: ", VERSION, " ***");
print ("***    Runtime -", current_time, "    ***");


# Before we start to collect anything, we need to see if we hit our fatal error threshold. 
ecount = read_counter_value();

if DEBUG2 == True:
  print ("DEBUG: Got (", ecount, ") from file...");

if (ecount >= THRESHOLD):
  print ("")
  print ("Unfortunately, we have hit the max number of retries after a fatal error.");
  print ("Note, if you repaired the connectivity issues, simply delete the file: ", TMPFILE)
  print ("and start this program again. ");
  print ("BAILING OUT!!");
  sys.exit(2)


# We are good, not past the threshold. 
print ("")
print ("Collect raw Mate3s API Data from IP: %s..." %MATE3S_API_IP_ADDRESS)

mate3s_api_url = "http://" + MATE3S_API_IP_ADDRESS + "/Dev_status.cgi?Port=0"

# 
# Set up the http Request Headers - Lets be complete... 
#
#User-Agent': 
h_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; Raspi 4b;) KnightWebKit/6.4.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36'
#Accept: 
h_accept = 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9'
#Accept-Encoding: 
h_accept_encoding = 'gzip, deflate'
#Cache-Control: 
h_cache_control = 'no-cache'
#Connection: 
h_connection = 'keep-alive'
#Pragma: 
h_pragma = 'no-cache'

# Lets run with the request while building the complete header above
req = urllib.request.Request(
  mate3s_api_url, 
  data=None, 
  headers={
    'User-Agent': h_user_agent,
    'Accept': h_accept,
    'Accept-Encoding': h_accept_encoding,
    'Cache-Control': h_cache_control,
    'Connection': h_connection,
    'Pragma': h_pragma
  })


# Lets get the data - and catch as many exceptions as possible. 
while True:
  try: 

    f = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)

  except HTTPError as error:
    print("Data not retrieved because of this error:");
    print(error);
    print("Retrying...");
    continue;

  except URLError as error:
    print('URLError caught after %d seconds - because of this error:' %HTTP_TIMEOUT);
    print(error);

    #print ("errno is: (", error.errno, ")")
    #print ("strerror is: (", error.strerror, ")")
    #print("The error string is: (",error,")");
    #print("The error.errno string is: (",error.errno,")");
    #print("The error.reason string is: (",error.reason,")");

    #Check for "Errno 113 in the string : " [Errno 113] No route to host "
    substring1 = "Errno 113"
    substring2 = "Errno 111"

    if ( (substring1 in str(error)) or (substring2 in str(error)) ):
        print ("Notice: We got a connection timeout to the IP!! ALERT THE DOGS! Recheck mate3s and send alarm");

 	# Update the threshold value of system - to use later in other logic.
        # The issue is if this is a daemon, and restarting all the time, if the mate3 loses its brain, 
        # we will continue to get alarms on our phones. .... so, to stop that, send THRESHOLD times, and then 
	# don't send again. 

        ecount = ecount + 1
        write_counter_value(ecount);

        # Email the alerts and send to pager or whatever. 

        # It is assumed that sendmail works locally from your computer - if not, you need to figure that out. 
        # Use mailx, which is part of mailutils. 
        t = time.localtime()
        current_time = time.strftime("%Y%m%d %H:%M:%S", t)
        EMAIL_SUBJECT = "Alert: Mate3S Connection Failure" 

        #EMAIL_BODY = str(current_time) + ": Mate3s Connection Failure to " + str(MATE3S_API_IP_ADDRESS) + ": "
        #EMAIL_BODY = EMAIL_BODY + "Alert " + str(ecount) + " of " + str(THRESHOLD) + ": " + str(error.reason)

        EMAIL_BODY = str(current_time) + ": Alert " + str(ecount) + " of " + str(THRESHOLD) + ": " + str(error.reason) + " (" + str(MATE3S_API_IP_ADDRESS) + ")"

        print (EMAIL_BODY);
        SYSTEM_COMMAND= "echo '" + EMAIL_BODY + "' | mailx -s '" + EMAIL_SUBJECT + "' " + EMAIL_RECIPIENTS
        os.system(SYSTEM_COMMAND);
        print ("Email sent Successfully.");

        print ("BYE BYE.");
        sys.exit(99)
   
    print("Retrying...");
    continue;

  except socket.timeout as error:
    print("socket.timeout caught after %s seconds - because of this error:" %HTTP_TIMEOUT);
    print(error);
    print("Retrying...");
    continue;

  except JSONDecodeError as error:
    print("JSONDecodeError caught because of this error:")
    print(error);
    print("Retrying...");
    continue;

  except ValueError:  			# includes simplejson.decoder.JSONDecodeError
    print ("After fetch, decoding Json has failed - caught with this error:");
    print(error);
    print("Retrying...");
    continue;

  else:
    print('Mate3s API Data Connection: Successful')
    break;

  print("We received and caught a system error from urllib.request.urlopen... ");
  print("Lets try again...");

  continue;


#
# At this point, we know we were able to connect (regardless of whether the data is toast)
# so, lets clear the error counter file. 
#
clear_counter_value()

#
# We have connection- so continue and read the data. 
#
response = f.read();

# Fill MQTT_MSG with the response data just read... 
# Note, comment out to use the sample data defined above. 
MQTT_MSG = response;

#
# Load the json into "j" for use down the line. 
#
try: 
  j = json.loads(MQTT_MSG);		# Note, this is also done down below in on_connect handler

except ValueError:  				# includes simplejson.decoder.JSONDecodeError
  print ("Json.Loads has failed - caught with some kind of error");
  print ("We could try to figure it out some more, but - this happens sometimes due to network latency. ");
  print ("Timeout is set to %s seconds, you might try increasing the value." %HTTP_TIMEOUT);
  print ("That's ok... lets just exit - we'll get more data during the next run. ");
  print ("Bye bye!!");
  sys.exit(1);

else:
  print('Json.Loads and Validation: Successful')




#
# Just a quick sanity check - sometimes, we get a complete json load, but the data
# is not complete... ie port1, or 2 is missing. 
# So, lets check to see if length of port 2 > 0... if so, then we have all the data. 
#

num_ports = len(j["devstatus"]["ports"]);

if (num_ports == NUM_PORTS):
  print ("Json Data Sanity Check: Successful");
else: 
  print ("Json Data Sanity Check: FAILED with ", num_ports, " ports of data");
  print ("Some data is missing.  This happens sometimes.  ");
  print ("No worries, we'll get it the next time around ");
  print ("Bye Bye");
  sys.exit(2);
  
################################################################################
#
# The DEBUG Block after we read the data... Not needed in production

if DEBUG1 == True:
  print ("");
  print ("DEBUG1: Here is the full response payload as received from the mate3s")
  print ("");
  print(response)
  print ("");

  # j = json.loads(MQTT_MSG);		# Note, this is also done down below in on_connect handler

if DEBUG2 == True:
  print ("MQTT_MSG is: ", MQTT_MSG)
  print("MQTT_MSG is a ", type(MQTT_MSG));
  print;

  print ("j is a ", type (j));
  print ("j is: ", j)

  # Some data for debug.
  print("j.devstatus = ", j["devstatus"]);
  print;
  
  print("j.Gateway_type = ", j["devstatus"]["Gateway_Type"]);
  print;
  
  print("j.ports.0 = ", j["devstatus"]["ports"][0]);
  print;
  
  ports0 = j["devstatus"]["ports"][0];
  print("ports0 = ", ports0);
  print;

################################################################################
#
# Get my current IP Address - there will alwas be exactly one (not your loopback). 
# We might need this for mqtt stuff, not a bad idea to collect and send along with
# a payload

interfaces = netifaces.interfaces()
for ifacename in interfaces:
    # Skip the loopback interface (127.0.0.1)
    if ifacename == 'lo' or ifacename == 'lo0':
        continue

    iface = netifaces.ifaddresses(ifacename).get(netifaces.AF_INET)
    if iface != None:
        for addr in iface:
            MY_IP_ADDRESS = addr['addr']
            break

if DEBUG2 == True:
  print ("DEBUG2: IP Address discovered: ", MY_IP_ADDRESS);

################################################################################
# 
# Get my mac address- this implies I know my IP Address (Gotten above)
# We might need this for mqtt stuff, not a bad idea to collect and send along with
# a payload
#

MY_MAC_ADDRESS=getmac.get_mac_address(ip=MY_IP_ADDRESS, network_request=MQTT_RETAIN);
if (MY_MAC_ADDRESS is None):
  MY_MAC_ADDRESS=getmac.get_mac_address(interface=ETH_INTERFACE);

if DEBUG2 == True:
  print ("DEBUG2: Mac address discovered: ", MY_MAC_ADDRESS);

################################################################################
#
# Calculate current panel input wattage
# We will add this to a topic below. 
# Watts = Amps * Volts 
#	( Watts = Shunt_B_I * Batt_V)
#
PV_Watts = (j["devstatus"]["ports"][2]["Batt_V"] * j["devstatus"]["ports"][2]["Shunt_B_I"]) 
#print ("Debug: PV_Watts = ", PV_Watts);
if (PV_Watts <= 0): 
  PV_Watts = 0.0;

################################################################################
#
# Calculate current PV System Load
# We will add this to a topic below. 
# We have the amps and volts - like the PV_Watts above, 
# Remember: # Watts = (Amps * Volts)
# so the basic calculation for AC Load for this system is
#	(PV_Load_Watts = Inv_I_L2 * VAC_out_L2)
#
# Note, If we were on grid, we would have to factor in  buying and selling 
#  to/from grid.  I'm not sure of those are amps or vac, (I think they are amps)
#  so it will have to wait, but the basic calculation is 
#  Invert (from battery) in watts - sell to grid in watts + buy from grid in watts. 
#  Or PV_Load - (("Buy_I_L2*vac_out_l2") + ("Sell_I_L2*vac_out_l2))
#  This would be calculated if ONGRID was set to True. 
#
# But since we are off grid, I'll just leave it like that. 
#
i_inv_i_l2 = j["devstatus"]["ports"][0]["Inv_I_L2"]
i_vac_out_l2 = j["devstatus"]["ports"][0]["VAC_out_L2"]

PV_Load = (i_inv_i_l2 * i_vac_out_l2);

if DEBUG2 == True:
  print ("Debug: i_inv_i_l2 = ", i_inv_i_l2);
  print ("Debug: i_vac_out_l2 = ", i_vac_out_l2);
  print ("Debug: i_buy_i_l2 = ", i_buy_i_l2);
  print ("Debug: i_sell_i_l2 = ", i_sell_i_l2);

if ONGRID == True: 
  i_sell_i_l2 = (j["devstatus"]["ports"][0]["Sell_I_L2"] * i_vac_out_l2)
  i_buy_i_l2 = (j["devstatus"]["ports"][0]["Buy_I_L2"] * i_vac_out_l2)
  PV_Load = PV_Load - (i_buy_i_l2 + i_sell_i_l2)

# Just normalize it. 
if (PV_Load <= 0): 
  PV_Load = 0.0;

################################################################################

# Convert system time to human readable time string.  
epoch_value = j["devstatus"]["Sys_Time"]
human_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(epoch_value));


# Some data for debug.
if DEBUG1 == True:

  print;
  print("Mate3s System Time: ", epoch_value, " / Converted to Local Time: ", human_time);
  print("Current Battery Voltage: " + str(j["devstatus"]["ports"][2]["Batt_V"]) + 
	" Vdc / State of Charge: " + str(j["devstatus"]["ports"][2]["SOC"]) + " %");

  print("Curent Solar Energy from Panels = %5.2f Watts" %(PV_Watts));
  print("Curent PV Load = %5.2f Watts" %(PV_Load));


  print ("");

if DEBUG2 == True:
  print;
  print ("DEBUG2: basic information received... load the content now into MQTT... ");



####################### PAUSE HERE #############################################
if DEBUG3 == True:
  cont=input("enter to continue")
################################################################################

if DEBUG2 == True:
  # Display Ports Information for Payload... this is the code used for 
  # identifying how all this plays together... we can remove for mainline
  # code.   This is output simply for review purposes. 
  print (' \n Port 0 Values \r ');
  
  THIS_TOPIC = MQTT_TOPIC + "/port0/"
  for key, val in ports0.items():
   print ("\nKey Value pair: key is: ", key , "and val is: ", val)
   THIS_TOPIC = MQTT_TOPIC + "/ports0/" + key 
   print ("value is type ", type(val));
   print ("value of ports0[key] = ", ports0[key]);
   print ("type of ports0[key] = ", type(ports0[key]));
   print ("TOPIC : ",THIS_TOPIC)
  
   if (type(ports0[key]) is list):
      numfields = len(ports0[key])
  
      # Publish the index as topic
      THIS_TOPIC = MQTT_TOPIC + "/ports0/" + key + "/count";
      print("THIS_TOPIC is now: ", THIS_TOPIC);
      #print("   client.subscribe(THIS_TOPIC); ");
      #print("   client.publish(THIS_TOPIC, numfields, qos=0, retain=MQTT_RETAIN); ");
  
      # Publish all of the list values. 
      cntr=0
      print ("there are ", numfields , " elements in the list");
      for i in ports0[key]:
        print ("type of list value is: ", type(i))
        print ("list value number: ", cntr , " is ", i);
  
        THIS_TOPIC = MQTT_TOPIC + "/ports0/" + key + "/" + str(cntr);
        print("THIS_TOPIC is now: ", THIS_TOPIC);
        #print("   client.subscribe(THIS_TOPIC); ");
        #print("   client.publish(THIS_TOPIC, i, qos=0, retain=MQTT_RETAIN); ");
        cntr = cntr+1;
  
   else:
       print ("It is not a list... ");
       #print("   client.subscribe(THIS_TOPIC); ");
       #print("   client.publish(THIS_TOPIC, ports0[key], qos=0, retain=MQTT_RETAIN); ");
  
####################### PAUSE HERE #############################################
if DEBUG3 == True:
  cont=input("enter to continue")
################################################################################



################################################################################
############################# HELPER FUNCTIONS ################################
################################################################################

#########################################
# on_publish Handler 
#########################################

# Define on_publish event function
def on_publish(client, userdata, mid):
  if DEBUG2 == True:
    print ("Message Published...");

#########################################
# on_connect Handler 
#########################################

def on_connect(client, userdata, flags, rc):

  # Did we connect ok 
  if rc == 0:
        print("MQTT Server Connection: Successful");
  else:
        print("MQTT Server Connection Failed - Return Code: ",rc)
	# We probably should catch exceptions and explain why... but whatever. 
        sys.exit(1);

  ########################################
  # Subscribe to all of the topics. 
  #
  # Rule for mqtt, do all the subscribes at the top first... 
  # Then we can publish to those topics. 
  # So, here goes. 
  # 
  # Note, the port numbers will change for other configurations... 
  # This is hard coded for Howie's configuration - 
  # If this is used in other places, you will have to adjust your 
  # ports to be correct. 
  ########################################

  # Mate3s Specific - top (From Json)
  THIS_TOPIC = MQTT_TOPIC + "/Gateway_Type";
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/Sys_Time_Epoch";
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/Sys_Time_Human";
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/Sys_Batt_V";
  client.subscribe(MQTT_TOPIC);

  # Topics - top level  (SYSInfo)
  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/CC_Model";
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/INV_Model";
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/MQTT_MAC_Address";
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/MQTT_IP_Address";
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/MATE3S_API_IP_Address";
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/PV_Watts";
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/PV_Load";
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/Battery_Capacity" 
  client.subscribe(MQTT_TOPIC);

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/Battery_Type" 
  client.subscribe(MQTT_TOPIC);

  # Topics - each port connected to mate3s. (from json)

  ports0 = j["devstatus"]["ports"][0];	# Port 0 is the Inverter (FXR 3048 Sealed 120V Model)
  ports1 = j["devstatus"]["ports"][1];	# Port 1 is the Charge Controller (FM100)
  ports2 = j["devstatus"]["ports"][2];	# Port 2 is the FNDC (FlexNet DC Controller)

  # subscribe and save whole json connection (just in case we want to use that also at some point)
  THIS_TOPIC = MQTT_TOPIC + "/json"
  client.subscribe(THIS_TOPIC);

  # All the ports - adjust your numbers.
  for key, val in ports0.items():
     THIS_TOPIC = MQTT_TOPIC + "/ports0/" + key 
     client.subscribe(THIS_TOPIC); 

  for key, val in ports1.items():
     THIS_TOPIC = MQTT_TOPIC + "/ports1/" + key 
     client.subscribe(THIS_TOPIC); 

  for key, val in ports2.items():
     THIS_TOPIC = MQTT_TOPIC + "/ports2/" + key 
     client.subscribe(THIS_TOPIC); 

  ########################################
  # Publish the whole json. 
  # and everythign else.... 
  ########################################

  THIS_TOPIC = MQTT_TOPIC + "/json"
  client.publish(THIS_TOPIC, MQTT_MSG, qos=0, retain=MQTT_RETAIN);

  print ("Json published to MQTT: Successful");

  #print;
  #print("MQTT_MSG is a ", type(MQTT_MSG));


  # Mate3s Specific - top from json
  THIS_TOPIC = MQTT_TOPIC + "/Gateway_Type"
  client.publish(THIS_TOPIC, j["devstatus"]["Gateway_Type"], qos=0, retain=MQTT_RETAIN);	

  THIS_TOPIC = MQTT_TOPIC + "/Sys_Time_Epoch"
  client.publish(THIS_TOPIC, j["devstatus"]["Sys_Time"], qos=0, retain=MQTT_RETAIN);	

  THIS_TOPIC = MQTT_TOPIC + "/Sys_Time_Human"
  client.publish(THIS_TOPIC, human_time, qos=0, retain=MQTT_RETAIN);	

  THIS_TOPIC = MQTT_TOPIC + "/Sys_Batt_V"
  client.publish(THIS_TOPIC, j["devstatus"]["Sys_Batt_V"], qos=0, retain=MQTT_RETAIN);	


  # Topics - "sysinfo" Defitions
  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/CC_Model" 
  client.publish(THIS_TOPIC, MATE3S_CC_MODEL, qos=0, retain=MQTT_RETAIN);		

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/INV_Model"
  client.publish(THIS_TOPIC, MATE3S_INV_MODEL, qos=0, retain=MQTT_RETAIN);	

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/MQTT_IP_Address"
  client.publish(THIS_TOPIC, MY_IP_ADDRESS, qos=0, retain=MQTT_RETAIN);	

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/MQTT_MAC_Address"
  client.publish(THIS_TOPIC, MY_MAC_ADDRESS, qos=0, retain=MQTT_RETAIN);	

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/MATE3S_API_IP_Address"
  client.publish(THIS_TOPIC, MATE3S_API_IP_ADDRESS, qos=0, retain=MQTT_RETAIN);	

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/PV_Watts"
  client.publish(THIS_TOPIC, round(PV_Watts,2), qos=0, retain=MQTT_RETAIN);	

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/PV_Load"
  client.publish(THIS_TOPIC, round(PV_Load,2), qos=0, retain=MQTT_RETAIN);	

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/Battery_Capacity" 
  client.publish(THIS_TOPIC, MATE3S_BATTERY_CAPACITY, qos=0, retain=MQTT_RETAIN);		

  THIS_TOPIC = MQTT_TOPIC + "/sysinfo/Battery_Type" 
  client.publish(THIS_TOPIC, MATE3S_BATTERY_TYPE, qos=0, retain=MQTT_RETAIN);		

  #########################################
  # Publish all the values of ports[0]
  # The Inverter
  #########################################

  for key, val in ports0.items():
    
    # Deal with the items and lists differently
    # Topics can only have strings, integers, floats, 
    # lists will be broken apart into their individual parts, 
    # with count topic added for each. 
 
    if (type(ports0[key]) is list):
       numfields = len(ports0[key])
    
       # Publish the index as topic
       THIS_TOPIC = MQTT_TOPIC + "/ports0/" + key + "/count";
       client.subscribe(THIS_TOPIC); 
       client.publish(THIS_TOPIC, numfields, qos=0, retain=MQTT_RETAIN); 
    
       # Publish all of the list values. 
       cntr=0

       for i in ports0[key]:
         #print ("type of list value is: ", type(i))
         #print ("list value number: ", cntr , " is ", i);
    
         THIS_TOPIC = MQTT_TOPIC + "/ports0/" + key + "/" + str(cntr);

         if DEBUG2 == True:
           print("THIS_TOPIC is now: ", THIS_TOPIC);

         client.subscribe(THIS_TOPIC); 
         client.publish(THIS_TOPIC, i, qos=0, retain=MQTT_RETAIN); 

         cntr = cntr + 1;
    
    else:

       # Publish all the other data in this port
       THIS_TOPIC = MQTT_TOPIC + "/ports0/" + key;

       if DEBUG2 == True:
         print("THIS_TOPIC is now: ", THIS_TOPIC);

       client.publish(THIS_TOPIC, ports0[key], qos=0, retain=MQTT_RETAIN); 
    

  #########################################
  # Publish all the values of ports[1]
  # The Charge Controller
  #########################################

  for key, val in ports1.items():
    
    if (type(ports1[key]) is list):
       numfields = len(ports0[key])
    
       THIS_TOPIC = MQTT_TOPIC + "/ports1/" + key + "/count";
       client.subscribe(THIS_TOPIC); 
       client.publish(THIS_TOPIC, numfields, qos=0, retain=MQTT_RETAIN); 
    
       cntr=0

       for i in ports1[key]:
    
         THIS_TOPIC = MQTT_TOPIC + "/ports1/" + key + "/" + str(cntr);

         if DEBUG2 == True:
           print("THIS_TOPIC is now: ", THIS_TOPIC);

         client.subscribe(THIS_TOPIC); 
         client.publish(THIS_TOPIC, i, qos=0, retain=MQTT_RETAIN); 
         cntr = cntr + 1;
    
    else:

       THIS_TOPIC = MQTT_TOPIC + "/ports1/" + key;

       if DEBUG2 == True:
         print("THIS_TOPIC is now: ", THIS_TOPIC);

       client.publish(THIS_TOPIC, ports1[key], qos=0, retain=MQTT_RETAIN); 


 #########################################
 # Publish all the values of ports[2]
 # The FNDC
 #########################################

  for key, val in ports1.items():
     THIS_TOPIC = MQTT_TOPIC + "/ports1/" + key 
    
     if (type(ports1[key]) is list):
       numfields = len(ports1[key])
    
       THIS_TOPIC = MQTT_TOPIC + "/ports1/" + key + "/count";
       client.subscribe(THIS_TOPIC); 
       client.publish(THIS_TOPIC, numfields, qos=0, retain=MQTT_RETAIN); 
    
       cntr=0

       for i in ports1[key]:
    
         THIS_TOPIC = MQTT_TOPIC + "/ports1/" + key + "/" + str(cntr);

         if DEBUG2 == True:
           print("THIS_TOPIC is now: ", THIS_TOPIC);

         client.subscribe(THIS_TOPIC); 
         client.publish(THIS_TOPIC, i, qos=0, retain=MQTT_RETAIN); 

         cntr = cntr + 1;
    
     else:

       THIS_TOPIC = MQTT_TOPIC + "/ports1/" + key;

       if DEBUG2 == True:
         print("THIS_TOPIC is now: ", THIS_TOPIC);

       client.publish(THIS_TOPIC, ports1[key], qos=0, retain=MQTT_RETAIN); 

  #########################################
  # Publish all the values of ports[3]
  # The FNDC
  #########################################

  for key, val in ports2.items():
     THIS_TOPIC = MQTT_TOPIC + "/ports2/" + key 
    
     if (type(ports2[key]) is list):
       numfields = len(ports2[key])
    
       THIS_TOPIC = MQTT_TOPIC + "/ports2/" + key + "/count";
       client.subscribe(THIS_TOPIC); 
       client.publish(THIS_TOPIC, numfields, qos=0, retain=MQTT_RETAIN); 
    
       cntr=0

       for i in ports2[key]:
    
         THIS_TOPIC = MQTT_TOPIC + "/ports2/" + key + "/" + str(cntr);

         if DEBUG2 == True:
           print("THIS_TOPIC is now: ", THIS_TOPIC);

         client.subscribe(THIS_TOPIC); 
         client.publish(THIS_TOPIC, i, qos=0, retain=MQTT_RETAIN); 

         cntr = cntr + 1;
    
     else:

       THIS_TOPIC = MQTT_TOPIC + "/ports2/" + key;

       if DEBUG2 == True:
         print("THIS_TOPIC is now: ", THIS_TOPIC);

       client.publish(THIS_TOPIC, ports2[key], qos=0, retain=MQTT_RETAIN); 


#########################################
# on_Message Handler 
#########################################

def on_message(client, userdata, msg):

  if DEBUG2 == True:
    print;
    print ("Message.Topic");
    print(msg.topic)
    print;

    print ("Message.Payload");
    print(msg.payload) # 
    print;

#########################################
# on_disconect Handler 
#########################################

def on_disconnect(client, userdata,rc=0):
    logging.debug("DisConnected result code "+str(rc))

    print ("DisConnected result code "+str(rc))

    mqttc.loop_stop()


################################################################################
#####################  Mainline Control Code.  #################################
################################################################################


# Initiate MQTT Client
mqttc = mqtt.Client()

# Register publish callback function
mqttc.on_publish = on_publish
mqttc.on_connect = on_connect
mqttc.on_message = on_message

# Connect with MQTT Broker and make it happen, 
#mqttc.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)    #set username and password
mqttc.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)    #set username and password
#mqttc.tls_set();
mqttc.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE_INTERVAL)
print("Connecting to the MQTT Server...");
mqttc.loop_start()
time.sleep (4)		# Just to make sure all finished 
mqttc.disconnect() 	# on Got disconnect message stop looping. 

print ("All topics sent to MQTT: Successful");

