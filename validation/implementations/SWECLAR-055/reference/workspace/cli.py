"""Supplied JSON console: domain actions or one bounded MQTT batch."""
import json,sys
from solution import process_iot_action,ingest_mqtt
value=json.load(sys.stdin)
if 'mqtt' in value:result=ingest_mqtt(value['state'],**value['mqtt'])
else:result=process_iot_action(value['state'],value['action'])
print(json.dumps(result,allow_nan=False))
