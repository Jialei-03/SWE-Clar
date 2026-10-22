"""Protected expectations; the Flutter worker receives only generic operations."""
from pathlib import Path
import sys,json,base64,io,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,'/public_tests')
from service_support import run_session,CandidateFailure
import struct,zlib

def main():
 if not Path('/public_tests/service_driver_test.dart').is_file():return {'harness_ok':False,'results':[],'infrastructure_errors':['Missing public operation adapter']}
 seen=[];attempts={}
 class H(BaseHTTPRequestHandler):
  def respond(self,value,status=200):self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(value).encode())
  def do_POST(self):
   payload=b''
   if self.headers.get('Transfer-Encoding','').lower()=='chunked':
    while True:
     size=int(self.rfile.readline().split(b';',1)[0],16)
     if size==0:self.rfile.readline();break
     payload+=self.rfile.read(size);self.rfile.read(2)
   else:payload=self.rfile.read(int(self.headers.get('Content-Length','0')))
   body=json.loads(payload);seen.append([self.command,self.path,body]);key=(self.server.scenario,self.path);attempts[key]=attempts.get(key,0)+1
   status=401 if key==('login-failure','/login') and attempts[key]==1 else 503 if key==('book-failure','/appointments') and attempts[key]==1 else 200
   self.respond({'id':'wire-user'} if self.path.endswith('/login') else {'id':'wire-appointment','service_id':'wire-service','slot':'15:00'},status)
  def do_GET(self):
   seen.append([self.command,self.path,None]);self.respond([] if self.server.scenario=='probe' else [{'id':'wire-service','title':'Wire service','available_slots':['15:00']}])
  def log_message(self,*a):pass
 servers={}
 for scenario in ['probe','login-failure','book-failure']:
  server=ThreadingHTTPServer(('127.0.0.1',0),H);server.scenario=scenario;servers[scenario]=server;threading.Thread(target=server.serve_forever,daemon=True).start()
 server=servers['probe']
 ops=[];index={};groups={}
 def add(label,op,**fields):index[label]=len(ops);ops.append({'op':op,**fields})
 def reset(name,**fields):add(name,'reset',**fields)
 def login(name):add(name,'login',username='tester',password='synthetic')
 def book(name,service='consultation',slot='09:00'):add(name,'book',service_id=service,slot=slot)
 def begin(name,method='book',**fields):add(name,'begin',method=method,**fields)
 def group(n):groups[n]=len(ops)
 group(1);reset('reset1',notifications={'copy':{'read':False,'destination':'dashboard'}});add('copied','mutate_original',id='copy',value={'read':True});add('mount1','mount');add('username','enter_text',key='username',text='tester');add('password','enter_text',key='password',text='synthetic');add('dashboard','tap',key='login');add('capture','capture',name='dashboard.png');add('wide','viewport',width=768,height=800);add('wire','http_probe',base_url=f'http://127.0.0.1:{server.server_port}')
 group(2);reset('reset2');add('guard','navigate',route='appointments');add('fail_config','configure',api={'fail':True});login('login_fail');add('clear','configure',api={});add('mount2','mount');login('good_login');add('unknown','navigate',route='invalid');add('logout','tap',key='logout')
 add('hold_login','hold',method='login');begin('begin_login',method='login',username='tester',password='synthetic');add('logout_pending','logout');add('finish_login','complete',value={'id':'late-user'});login('login_again');add('hold_book','hold',method='book');begin('begin_book',service_id='consultation',slot='09:00');add('logout_book','logout');add('finish_book','complete',value={'id':'late','service_id':'consultation','slot':'09:00'})
 add('invalid_user','configure',api={'login':{'id':''}});login('invalid_login');add('invalid_catalog','configure',api={'services':[{'id':'bad','title':'Bad','available_slots':[13]}]});login('bad_catalog')
 group(3);reset('reset3');add('mount3','mount');login('login3');add('book_tap','tap',key='book-consultation-09:00');book('duplicate');add('hold3','hold',method='book');begin('begin3',service_id='followup',slot='13:00');book('busy3','followup','13:00');add('finish3','complete',value={'id':'second','service_id':'followup','slot':'13:00','extra':'allowed'})
 group(4);reset('reset4');add('mount4','mount');login('login4');book('unknown_service','missing');book('bad_slot',slot='00:00');add('fail4','configure',api={'fail':True});book('failed');add('mismatch','configure',api={'book':{'id':'wrong','service_id':'other','slot':'09:00'}});book('mismatched');add('clear4','configure',api={});book('retry');add('sameid','configure',api={'book':{'id':'appointment-3','service_id':'followup','slot':'13:00'}});book('id_conflict','followup','13:00')
 group(5);notices={'one':{'read':False,'destination':'appointments','title':'Synthetic notice'},'two':{'read':False,'destination':'dashboard'},'bad':{'read':False,'destination':'invalid'}};reset('reset5',notifications=notices);add('unauth_notice','notification',id='one');add('mount5','mount');login('login5');add('notifications','tap',key='notifications');add('read','tap',key='notification-one');add('missing','notification',id='missing');add('bad','notification',id='bad')
 # The generic worker drives the actual HTTP adapter and controller.
 groups[6]=len(ops)  # Additional transport probes are asserted by check4, not RU-005.
 login_step={'method':'login','username':'wire-user','password':'wire-password'}
 book_step={'method':'book','service_id':'wire-service','slot':'15:00'}
 add('wire_login_failure','http_flow',base_url=f'http://127.0.0.1:{servers["login-failure"].server_port}',steps=[login_step,login_step])
 add('wire_book_failure','http_flow',base_url=f'http://127.0.0.1:{servers["book-failure"].server_port}',steps=[login_step,book_step,book_step])
 try:
  result=run_session(ops,initial={});rows=result['observations']
 except CandidateFailure as e:return {'harness_ok':True,'results':[{'ru_id':f'RU-{i:03}','passed':False,'detail':str(e)[-1600:]} for i in range(1,6)]}
 finally:
  for server in servers.values():server.shutdown();server.server_close()
 def r(name):return rows[index[name]]
 def calls(name,method):return [x for x in r(name)['calls'] if x['method']==method]
 def error(name,code):assert r(name)['error']==code
 def unchanged(name,base):
  for key in ['user','route','appointments','notifications']:assert r(name)[key]==r(base)[key],(name,key)
 def check1():
  assert r('copied')['notifications']['copy']['read'] is False and r('copied')['original_notifications']['copy']['read'] is True
  assert 'General consultation' in r('dashboard')['texts'] and 'book-consultation-09:00' in r('dashboard')['keys'];assert 'General consultation' in r('wide')['texts']
  assert calls('dashboard','login')==[{'method':'login','username':'tester','password':'synthetic'}]
  assert [x[:2] for x in seen[:3]]==[['POST','/login'],['GET','/services'],['POST','/appointments']]
  assert all(seen[0][2].get(k)==v for k,v in {'username':'wire-user','password':'wire-password'}.items())
  assert all(seen[2][2].get(k)==v for k,v in {'service_id':'wire-service','slot':'15:00'}.items())
  assert r('wire')['http']['appointment']['id']=='wire-appointment'
  data=base64.b64decode(result['captures_base64']['dashboard.png']);assert data[:8]==b'\x89PNG\r\n\x1a\n' and struct.unpack('>II',data[16:24])==(360,900)
  at=8;compressed=b''
  while at<len(data):
   size=struct.unpack('>I',data[at:at+4])[0];kind=data[at+4:at+8]
   if kind==b'IDAT':compressed+=data[at+8:at+8+size]
   at+=size+12
  assert len(set(zlib.decompress(compressed)))>20
 def check2():
  error('guard','authentication_required');assert r('guard')['route']=='login';error('login_fail','api_failed');assert r('login_fail')['user'] is None
  assert r('good_login')['route']=='dashboard';error('unknown','unknown_route');assert r('unknown')['route']=='dashboard'
  for name in ['logout','logout_pending','finish_login','logout_book','finish_book']:
   assert r(name)['user'] is None and r(name)['route']=='login' and r(name)['appointments']=={} and not r(name)['busy'];assert 'username' in r(name)['keys']
  for name in ['invalid_login','bad_catalog']:error(name,'api_failed');assert r(name)['user'] is None and r(name)['route']=='login'
 def check3():
  assert len(calls('book_tap','book'))==1 and 'Your appointments' in r('book_tap')['texts'] and 'appointment-appointment-1' in r('book_tap')['keys']
  error('duplicate','duplicate_appointment');assert len(calls('duplicate','book'))==1
  assert len(calls('busy3','book'))==2 and r('busy3')['busy'];assert len(r('finish3')['appointments'])==2
 def check4():
  failed_login,retried_login=r('wire_login_failure')['http_flow']
  assert failed_login['error']=='api_failed' and failed_login['user'] is None and failed_login['route']=='login' and not failed_login['busy']
  assert retried_login['error'] is None and retried_login['route']=='dashboard'
  before,failed_booking,retried_booking=r('wire_book_failure')['http_flow']
  assert before['route']=='dashboard' and failed_booking['error']=='api_failed' and not failed_booking['busy']
  for key in ['user','route','appointments']:assert failed_booking[key]==before[key]
  assert retried_booking['error'] is None and retried_booking['route']=='appointments' and len(retried_booking['appointments'])==1
  error('unknown_service','unknown_service');error('bad_slot','unavailable_slot');assert calls('bad_slot','book')==[]
  for name in ['failed','mismatched']:error(name,'api_failed');assert r(name)['appointments']=={} and r(name)['route']=='dashboard';assert 'api_failed' in r(name)['texts']
  assert len(r('retry')['appointments'])==1 and r('retry')['error'] is None
  error('id_conflict','api_failed');unchanged('id_conflict','retry')
 def check5():
  error('unauth_notice','authentication_required');assert r('unauth_notice')['notifications']==notices
  assert r('read')['notifications']['one']['read'] is True and r('read')['notifications']['two']['read'] is False;assert r('read')['original_notifications']==notices
  assert r('read')['route']=='appointments' and 'Your appointments' in r('read')['texts'];error('missing','unknown_notification');error('bad','unknown_route');assert r('bad')['notifications']==r('read')['notifications']
 results=[]
 for i,check in enumerate([check1,check2,check3,check4,check5],1):
  try:
   for row in rows[groups[i]:groups.get(i+1,len(rows))]:assert not row.get('operation_error') and not row.get('render_errors'),row.get('operation_error') or row.get('render_errors')
   check();passed,detail=True,'passed'
  except Exception as e:passed,detail=False,type(e).__name__+': '+str(e)
  results.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
 return {'harness_ok':True,'results':results}
if __name__=='__main__':print(json.dumps(main()))
