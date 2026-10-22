"""Existing domain regressions and prepared dependency smoke checks."""
from copy import deepcopy
from importlib.metadata import version
import json,subprocess,sys
from pathlib import Path
assert version('paho-mqtt')=='2.1.0'
import paho.mqtt.client as mqtt
assert mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,protocol=mqtt.MQTTv311)
sys.path.insert(0,str(Path.cwd()))
from solution import process_iot_action
state={'users':{'admin':{'role':'tenant_admin'}},'entities':{},'devices':{'sensor':{'company_id':'c'}},'topics':{'synthetic/sensor':'sensor'},'rules':{}}
before=deepcopy(state)
created=process_iot_action(state,{'type':'create_entity','actor_id':'admin','entity_type':'company','entity_id':'company','name':'Example'})
assert created['entities']['company']['name']=='Example' and state==before
for ts,value in [(2,20),(1,10)]:state=process_iot_action(state,{'type':'ingest','topic':'synthetic/sensor','timestamp':ts,'payload':{'value':value}})
assert [r['timestamp'] for r in state['telemetry']['sensor']['value']]==[1,2]
request={'state':state,'action':{'type':'aggregate','device_id':'sensor','key':'value','start':1,'end':2}}
p=subprocess.run([sys.executable,'cli.py'],input=json.dumps(request),capture_output=True,text=True,check=True)
r=json.loads(p.stdout)['result'];assert all(r[k]==v for k,v in dict(count=2,min=10,max=20,mean=15).items())
import time
observed=[]
client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,protocol=mqtt.MQTTv311)
client.on_connect=lambda c,u,f,r,p:c.subscribe('synthetic/sensor',qos=0)
client.on_message=lambda c,u,msg:observed.append(json.loads(msg.payload))
client.connect('127.0.0.1',1883);deadline=time.monotonic()+2
while not observed and time.monotonic()<deadline:client.loop(timeout=.05)
client.disconnect()
assert observed==[{'timestamp':1,'values':{'value':20}}]
print('Prepared paho, live development broker, domain and JSON console regressions passed.')
