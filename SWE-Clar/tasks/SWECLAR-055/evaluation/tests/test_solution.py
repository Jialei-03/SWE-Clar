from copy import deepcopy
from conftest import load_solution

def _fcb_contains_expected_fields(actual, expected):
    return isinstance(actual, dict) and all((key in actual and actual[key] == value for key, value in expected.items()))

def base():
    return {'users': {'t': {'role': 'tenant_admin'}, 'a': {'role': 'company_admin', 'company_id': 'c1'}, 'b': {'role': 'company_admin', 'company_id': 'c2'}}, 'entities': {}, 'devices': {'d': {'company_id': 'c1', 'name': 'Sensor'}}, 'topics': {'care/d': 'd'}, 'rules': {'hot': {'key': 'temperature', 'operator': 'gt', 'threshold': 30}}}

def test_ru_001_immutable():
    m = load_solution()
    m.process_iot_action = _assert_result_contract(m.process_iot_action)
    s = base()
    old = deepcopy(s)
    m.process_iot_action(s, {'type': 'ingest', 'topic': 'care/d', 'timestamp': 1, 'payload': {'temperature': 31}})
    assert s == old

def test_ru_002_entity_roles():
    m = load_solution()
    s = base()
    s = m.process_iot_action(s, {'type': 'create_entity', 'actor_id': 't', 'entity_type': 'company', 'entity_id': 'c1', 'name': 'Care'})
    assert s['result']['entity_id'] == 'c1' and s['entities']['c1']['name'] == 'Care'
    s = m.process_iot_action(s, {'type': 'create_entity', 'actor_id': 'a', 'entity_type': 'device', 'entity_id': 'd2', 'company_id': 'c1', 'name': 'Sensor 2'})
    assert s['devices']['d2']['name'] == 'Sensor 2' and s['entities']['d2']['company_id'] == 'c1'
    s = m.process_iot_action(s, {'type': 'update_device', 'actor_id': 'a', 'device_id': 'd2', 'changes': {'name': 'Updated'}})
    assert s['devices']['d2']['name'] == 'Updated' and s['entities']['d2']['name'] == 'Updated'
    r = m.process_iot_action(s, {'type': 'create_entity', 'actor_id': 'b', 'entity_type': 'device', 'entity_id': 'x', 'company_id': 'c1'})
    assert r['error']['code'] == 'create_denied'
    r = m.process_iot_action(s, {'type': 'update_device', 'actor_id': 'b', 'device_id': 'd2', 'changes': {'name': 'Denied'}})
    assert r['error']['code'] == 'update_denied' and s['devices']['d2']['name'] == 'Updated'

def test_ru_003_ingest():
    m = load_solution()
    s = base()
    s = m.process_iot_action(s, {'type': 'ingest', 'topic': 'care/d', 'timestamp': 2, 'payload': {'temperature': 31, 'humidity': 50}})
    s = m.process_iot_action(s, {'type': 'ingest', 'topic': 'care/d', 'timestamp': 1, 'payload': {'temperature': 29}})
    assert [x['timestamp'] for x in s['telemetry']['d']['temperature']] == [1, 2]
    assert m.process_iot_action(s, {'type': 'ingest', 'topic': 'unknown', 'timestamp': 3, 'payload': {}})['error']['code'] == 'invalid_telemetry'

def test_ru_004_aggregate():
    m = load_solution()
    s = base()
    s = m.process_iot_action(s, {'type': 'ingest', 'topic': 'care/d', 'timestamp': 1, 'payload': {'temperature': 20}})
    s = m.process_iot_action(s, {'type': 'ingest', 'topic': 'care/d', 'timestamp': 2, 'payload': {'temperature': 40}})
    r = m.process_iot_action(s, {'type': 'aggregate', 'device_id': 'd', 'key': 'temperature', 'start': 1, 'end': 2})
    assert _fcb_contains_expected_fields(r['result'], {'count': 2, 'min': 20, 'max': 40, 'mean': 30})

def test_ru_005_alarm_dashboard():
    m = load_solution()
    s = base()
    s = m.process_iot_action(s, {'type': 'ingest', 'topic': 'care/d', 'timestamp': 1, 'payload': {'temperature': 31}})
    s = m.process_iot_action(s, {'type': 'ingest', 'topic': 'care/d', 'timestamp': 2, 'payload': {'temperature': 35}})
    assert list(s['alarms']) == ['d:hot'] and s['alarms']['d:hot']['status'] == 'active'
    r = m.process_iot_action(s, {'type': 'dashboard', 'user_id': 'a'})
    assert len(r['result']['devices']) == 1 and len(r['result']['alarms']) == 1
    assert not m.process_iot_action(s, {'type': 'dashboard', 'user_id': 'b'})['result']['devices']
    alarm_id = next(iter(s['alarms']))
    acknowledged = m.process_iot_action(s, {'type': 'ack_alarm', 'actor_id': 'a', 'alarm_id': alarm_id})
    assert acknowledged['alarms'][alarm_id]['status'] == 'acknowledged'
    s = m.process_iot_action(acknowledged, {'type': 'clear_alarm', 'actor_id': 'a', 'alarm_id': alarm_id})
    assert not m.process_iot_action(s, {'type': 'dashboard', 'user_id': 'a'})['result']['alarms']


def _assert_result_contract(function):
    """Verify the declared JSON-object entry contract on the RU-001 calls."""
    from copy import deepcopy
    import json

    def checked(*args, **kwargs):
        before = deepcopy((args, kwargs))
        result = function(*args, **kwargs)
        assert isinstance(result, dict), "entry point must return a JSON object"
        assert (args, kwargs) == before, "entry point mutated its inputs"
        json.dumps(result, allow_nan=False)
        return result

    return checked

from contextlib import contextmanager
from threading import Thread
import json,socket,time

def wire_string(value):
 data=value.encode();return len(data).to_bytes(2,'big')+data

def packet(header,body):
 length=len(body);prefix=bytearray([header])
 while True:
  byte=length%128;length//=128;prefix.append(byte|(128 if length else 0))
  if not length:break
 return bytes(prefix)+body

def receive(sock):
 def exact(n):
  data=b''
  while len(data)<n:
   chunk=sock.recv(n-len(data))
   if not chunk:raise EOFError()
   data+=chunk
  return data
 header=exact(1)[0];length=0;factor=1
 for _ in range(4):
  byte=exact(1)[0];length+=(byte&127)*factor;factor*=128
  if byte<128:break
 else:raise ValueError('malformed remaining length')
 return header,exact(length)

@contextmanager
def broker(messages,reject=False,sub_reject=False,expected_topics=None):
 expected_topics=set(expected_topics or ['care/d'])
 listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(4)
 port=listener.getsockname()[1];seen={'topics':[],'connect':False,'disconnect':False,'errors':[]}
 def serve():
  try:
   with listener.accept()[0] as conn:
    conn.settimeout(4);header,body=receive(conn)
    assert header==16 and body[:7]==b'\x00\x04MQTT\x04';seen['connect']=True
    conn.sendall(b'\x20\x02\x00'+(b'\x05' if reject else b'\x00'))
    if reject:return
    while not expected_topics.issubset(seen['topics']):
     header,body=receive(conn);assert header==130;mid=body[:2];i=2;requested=[]
     while i<len(body):
      n=int.from_bytes(body[i:i+2],'big');topic=body[i+2:i+2+n].decode();qos=body[i+2+n];assert qos==0
      requested.append(topic);i+=3+n
     seen['topics'].extend(requested)
     conn.sendall(packet(144,mid+bytes([128 if sub_reject else 0]*len(requested))))
     if sub_reject:return
    for topic,payload in messages:
     raw=payload if isinstance(payload,bytes) else json.dumps(payload).encode()
     frame=packet(48,wire_string(topic)+raw)
     # Deliberately split both header/remaining-length and JSON bytes.
     for start in range(0,len(frame),7):conn.sendall(frame[start:start+7])
    try:header,body=receive(conn);seen['disconnect']=header==224
    except (EOFError,ConnectionResetError):seen['disconnect']=True
  except (OSError,EOFError,AssertionError,ValueError) as exc:seen['errors'].append(type(exc).__name__)
 thread=Thread(target=serve,daemon=True);thread.start()
 try:yield port,seen
 finally:listener.close();thread.join(5)

def test_ru_001_actual_subscription_and_input_preservation():
 m=load_solution();s=base();before=deepcopy(s)
 with broker([('care/d',{'timestamp':5,'values':{'temperature':35}})]) as (port,seen):
  out=m.ingest_mqtt(s,'127.0.0.1',port,1,2)
 assert s==before and seen['connect'] and set(seen['topics'])=={'care/d'} and not seen['errors']
 assert out['result']['accepted']==1 and [(r['timestamp'],r['value']) for r in out['telemetry']['d']['temperature']]==[(5,35)]
 assert seen['disconnect']

def test_ru_002_device_ownership_cannot_be_changed():
 m=load_solution();s=base()
 out=m.process_iot_action(s,dict(type='update_device',actor_id='a',device_id='d',changes={'company_id':'c2'}))
 assert out['error']['code']=='update_denied' and out['devices']==s['devices']

def test_ru_003_mqtt_fragmentation_malformed_packets_and_order():
 m=load_solution();s=base();s['topics']['care/second']='d'
 messages=[('care/d',{'timestamp':8,'values':{'temperature':40,'note':'SYNTHETIC '*40}}),('care/d',b'{bad'),('care/d',{'timestamp':True,'values':{'temperature':300}}),('unknown',{'timestamp':4,'values':{'temperature':300}}),('care/second',{'timestamp':3,'values':{'temperature':20}}),('care/d',b'{"timestamp":NaN,"values":{}}')]
 with broker(messages,expected_topics=['care/d','care/second']) as (port,seen):out=m.ingest_mqtt(s,'127.0.0.1',port,len(messages),2)
 assert out['result']['received']==6 and out['result']['accepted']==2 and len(out['result']['errors'])==4
 assert set(seen['topics'])=={'care/d','care/second'} and not seen['errors']
 assert [x['timestamp'] for x in out['telemetry']['d']['temperature']]==[3,8]
 assert out['alarms']['d:hot']['value']==40
 with broker([],reject=True) as (port,seen):denied=m.ingest_mqtt(s,'127.0.0.1',port,1,1)
 assert denied['error']['code']=='mqtt_failed' and denied.get('telemetry',{})=={}
 with broker([]) as (port,seen):empty=m.ingest_mqtt(s,'127.0.0.1',port,1,.2)
 assert empty['error']['code']=='mqtt_failed'

def test_ru_004_boolean_values_are_not_measurements():
 m=load_solution();s=base()
 for ts,value in [(1,True),(2,20),(3,40),(4,'not numeric')]:s=m.process_iot_action(s,dict(type='ingest',topic='care/d',timestamp=ts,payload={'temperature':value}))
 out=m.process_iot_action(s,dict(type='aggregate',device_id='d',key='temperature',start=1,end=4))
 assert _fcb_contains_expected_fields(out['result'],dict(count=2,min=20,max=40,mean=30))

def test_ru_005_alarm_permissions_and_no_other_role_dashboard():
 m=load_solution();s=m.process_iot_action(base(),dict(type='ingest',topic='care/d',timestamp=1,payload={'temperature':35}))
 for action in ['ack_alarm','clear_alarm']:
  out=m.process_iot_action(s,dict(type=action,actor_id='b',alarm_id='d:hot'))
  assert out['error']['code']=='alarm_denied' and out['alarms']==s['alarms']
 s['users']['unprivileged']={'role':'viewer','company_id':'c1'}
 out=m.process_iot_action(s,dict(type='dashboard',user_id='unprivileged'))
 assert out.get('error') or (not out['result']['devices'] and not out['result']['alarms'])

def test_ru_001_supplied_console():
 import os,subprocess,sys
 from pathlib import Path
 root=Path(os.environ['CANDIDATE_ROOT'])
 action=dict(type='create_entity',actor_id='t',entity_type='company',entity_id='new',name='Synthetic company')
 p=subprocess.run([sys.executable,str(root/'cli.py')],input=json.dumps({'state':base(),'action':action}),text=True,capture_output=True,timeout=10,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
 assert p.returncode==0
 assert json.loads(p.stdout)['entities']['new']['name']=='Synthetic company'

def test_ru_003_rejection_and_batch_limit():
 m=load_solution();s=base()
 with broker([],sub_reject=True) as (port,seen):out=m.ingest_mqtt(s,'127.0.0.1',port,1,.5)
 assert out.get('error') and out.get('telemetry',{})=={} and out.get('alarms',{})=={}
 messages=[('care/d',{'timestamp':1,'values':{'temperature':20}}),('care/d',{'timestamp':2,'values':{'temperature':40}})]
 with broker(messages) as (port,seen):out=m.ingest_mqtt(s,'127.0.0.1',port,1,1)
 assert out['result']['received']==1 and out['result']['accepted']==1
 assert [(r['timestamp'],r['value']) for r in out['telemetry']['d']['temperature']]==[(1,20)]
 assert not out['alarms']
 # A malformed envelope is discarded as a unit; later valid messages still reach all keys.
 messages=[('care/d',{'timestamp':3,'values':[]}),('care/d',{'timestamp':4,'values':{'temperature':25,'humidity':60}})]
 with broker(messages) as (port,seen):out=m.ingest_mqtt(s,'127.0.0.1',port,2,1)
 assert out['result']['accepted']==1 and out['result']['received']==2
 assert len(out['result']['errors'])==1 and out['result']['errors'][0]['topic']=='care/d' and out['result']['errors'][0].get('code')
 assert out['telemetry']['d']['humidity'][0]['value']==60

def test_ru_004_range_and_nonfinite_filter():
 m=load_solution();s=base();s['telemetry']={'d':{'temperature':[{'timestamp':i,'value':v} for i,v in enumerate([999,10,True,float('inf'),float('nan'),'text',30,999])]}}
 out=m.process_iot_action(s,dict(type='aggregate',device_id='d',key='temperature',start=1,end=6))
 assert _fcb_contains_expected_fields(out['result'],dict(count=2,min=10,max=30,mean=20))
 empty=m.process_iot_action(s,dict(type='aggregate',device_id='d',key='temperature',start=2,end=5))
 assert empty.get('error') and empty['error'].get('code')

def test_ru_005_roles_thresholds_and_status_regressions():
 m=load_solution();s=base();s['rules']['cold']={'key':'temperature','operator':'lt','threshold':10}
 for value in [True,30,10]:
  out=m.process_iot_action(s,dict(type='ingest',topic='care/d',timestamp=1,payload={'temperature':value}))
  assert not out['alarms']
 s=m.process_iot_action(s,dict(type='ingest',topic='care/d',timestamp=1,payload={'temperature':9}))
 assert s['alarms']['d:cold']['status']=='active'
 s=m.process_iot_action(s,dict(type='ack_alarm',actor_id='t',alarm_id='d:cold'))
 assert s['alarms']['d:cold']['status']=='acknowledged'
 s=m.process_iot_action(s,dict(type='ingest',topic='care/d',timestamp=2,payload={'temperature':8}))
 assert len(s['alarms'])==1 and s['alarms']['d:cold']['status']=='acknowledged'
 out=m.process_iot_action(s,dict(type='clear_alarm',actor_id='t',alarm_id='d:cold'))
 assert out['alarms']['d:cold']['status']=='cleared'
 assert not m.process_iot_action(out,dict(type='dashboard',user_id='t'))['result']['alarms']


def test_ru_003_invalid_telemetry_preserves_business_state():
 m=load_solution();s=base()
 s=m.process_iot_action(s,dict(type='ingest',topic='care/d',timestamp=1,payload={'temperature':40}))
 for stamp in [True,'2',float('inf')]:
  out=m.process_iot_action(s,dict(type='ingest',topic='care/d',timestamp=stamp,payload={'temperature':50}))
  assert out.get('error',{}).get('code')=='invalid_telemetry'
  for key in ['telemetry','alarms','devices','entities']:
   assert out.get(key,{})==s.get(key,{})
