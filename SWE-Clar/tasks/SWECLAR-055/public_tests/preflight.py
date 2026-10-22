"""Prepare and probe the public development broker before candidate budget."""
import subprocess,sys,json,socket,time
from pathlib import Path

def listening():
    try:
        with socket.create_connection(('127.0.0.1',1883),timeout=.1):return True
    except OSError:return False
if not listening():
    with open('/tmp/sweclar-public-mqtt.log','a') as log:
        subprocess.Popen([sys.executable,'-I','/public_tests/broker.py'],user=1000,group=1000,extra_groups=[],stdout=log,stderr=log,start_new_session=True)
    deadline=time.monotonic()+3
    while not listening() and time.monotonic()<deadline:time.sleep(.02)
    assert listening(),'Public broker unavailable'
probe="""from importlib.metadata import version
import paho.mqtt.client as m,time,json
assert version('paho-mqtt')=='2.1.0'
values=[]
c=m.Client(m.CallbackAPIVersion.VERSION2,protocol=m.MQTTv311)
c.on_connect=lambda c,u,f,r,p:c.subscribe('synthetic/sensor',qos=0)
c.on_message=lambda c,u,msg:values.append(json.loads(msg.payload))
c.connect('127.0.0.1',1883)
end=time.monotonic()+2
while not values and time.monotonic()<end:c.loop(timeout=.05)
c.disconnect()
assert values==[{'timestamp':1,'values':{'value':20}}],values
"""
subprocess.run([sys.executable,'-I','-c',probe],user=1000,group=1000,extra_groups=[],check=True)
print(json.dumps({'passed':True,'paho-mqtt':'2.1.0','broker':'127.0.0.1:1883','prepared_before_budget':True}))
