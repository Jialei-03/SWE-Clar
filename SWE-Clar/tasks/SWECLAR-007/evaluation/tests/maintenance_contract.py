"""Independent private assertions over real Firestore data and public Flutter operations."""
import contextlib,copy,hashlib,http.server,json,os,sys,threading,traceback
from pathlib import Path
sys.path.insert(0,'/public_tests')
from maintenance_support import CandidateFailure,run_session,isolated_database
LOG=Path(os.environ.get('SWECLAR_LOG_DIR','/private/results'));LOG.mkdir(parents=True,exist_ok=True)

def sv(value):return {'stringValue':value}
def get(service,origin,path):
    code,data=service['request'](origin,'GET',service['DOCUMENTS']+'/'+path)
    if code!=200:raise RuntimeError('Independent database read failed: '+str(code))
    return data

def snapshot(service,origin,paths):return {path:get(service,origin,path) for path in paths}

def run(operations,origin,label):
    result=run_session(operations,origin=origin)
    result.pop('captures_base64',None)
    (LOG/(label+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    return result['observations']

def text(row,key):return row.get('keyed_texts',{}).get(key)
def value(row):
    assert 'candidate_error' not in row,row.get('candidate_error')
    return row['value']

@contextlib.contextmanager
def proxy(service,origin,before_commit=None,fail_first_reload=False):
    requests=[];failure_pending=[];lock=threading.Lock()
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def execute(self):
            size=int(self.headers.get('Content-Length','0'))
            data=json.loads(self.rfile.read(size)) if size else None
            requests.append({'method':self.command,'path':self.path,'body':data})
            if self.command=='POST' and self.path.endswith(':commit') and before_commit is not None:before_commit()
            with lock:
                fail_now=bool(failure_pending) and self.command=='GET'
                if fail_now:failure_pending.pop()
            if fail_now:status,reply=503,{'error':'Controlled post-commit reload failure'}
            else:
                status,reply=service['request'](origin,self.command,self.path,data)
                if fail_first_reload and self.command=='POST' and self.path.endswith(':commit') and status==200:
                    with lock:failure_pending.append(True)
            raw=json.dumps(reply).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        do_GET=execute;do_POST=execute;do_PATCH=execute;do_DELETE=execute
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port),requests
    finally:server.shutdown();server.server_close();worker.join(timeout=5)


def core():
    with isolated_database() as (service,origin):
        seed={f'clinics/item-{i:03}':{'name':sv('Synthetic '+str(i)),'keep':{'integerValue':str(i)}} for i in range(63)}
        service['seed'](origin,seed);before=snapshot(service,origin,seed)
        operations=[{'op':'list','collection':'clinics'},{'op':'get','path':'clinics/absent'},{'op':'list','collection':'empty_collection'},{'op':'normalize','collection':'../clinics','field':'clinic','target':'clinics'},{'op':'fail','method':'GET'},{'op':'list','collection':'clinics'},{'op':'get','path':'clinics/item-000'}]
        with proxy(service,origin) as (base,requests):rows=run(operations,base,'core')
        docs=value(rows[0]);assert len(docs)==63
        assert {d['name'].split('/')[-1]:d['fields'] for d in docs}=={p.split('/')[-1]:f for p,f in seed.items()}
        assert all('updateTime' in d for d in docs)
        assert value(rows[1]) is None and value(rows[2])==[]
        assert all('candidate_error' in rows[i] for i in [3,5,6])
        assert all(r['method']=='GET' for r in requests)
        assert snapshot(service,origin,seed)==before


def screens():
    with isolated_database() as (service,origin):
        seed={f'clinics/item-{i:02}':{'name':sv('Long synthetic clinic name '+str(i)+' / <b>literal</b>')} for i in range(35)}
        seed['providers/provider-a']={'name':sv('Provider only')};seed['bookings/booking-a']={'name':sv('Booking only')}
        service['seed'](origin,seed)
        rows=run([{'op':'mount'},{'op':'scroll','dy':-1200},{'op':'scroll','dy':-1600},{'op':'tap','key':'nav-providers'},{'op':'hold','method':'GET','path_contains':'/clinics'},{'op':'tap','key':'nav-clinics'},{'op':'tap','key':'nav-bookings'},{'op':'release'},{'op':'fail','method':'GET'},{'op':'tap','key':'refresh'},{'op':'fail','method':None},{'op':'tap','key':'refresh'},{'op':'viewport','width':768,'height':950}],origin,'screens')
        assert text(rows[0],'page-title')==['clinics'] and text(rows[0],'load-state')==['ready']
        assert any('<b>literal</b>' in str(t) for t in rows[0]['texts'])
        assert rows[0]['visible_records'] and rows[2]['visible_records']
        assert set(rows[2]['visible_records'])-set(rows[0]['visible_records']),'Scrolling did not expose different records'
        assert 'Provider only' in rows[3]['texts']
        assert text(rows[6],'page-title')==['bookings'] and 'Booking only' in rows[6]['texts']
        assert text(rows[7],'page-title')==['bookings'] and 'Booking only' in rows[7]['texts']
        assert 'Provider only' not in rows[7]['texts']
        assert text(rows[9],'load-state')==['error']
        assert text(rows[11],'load-state')==['ready'] and 'Booking only' in rows[11]['texts']
    with isolated_database() as (service,origin):
        rows=run([{'op':'mount'}],origin,'empty-screen')
        assert text(rows[0],'load-state')==['ready'] and text(rows[0],'empty-state')


def compatibility():
    with isolated_database() as (service,origin):
        prefix='projects/demo-sweclar/databases/(default)/documents/'
        seed={'clinics/c-a':{'name':sv('<b>Literal Clinic</b>')},'clinics/c-b':{'name':sv('')},'clinics/c-c':{'other':sv('fallback')}}
        forms=[('A',sv('c-a'),'c-a','<b>Literal Clinic</b>'),('B',{'referenceValue':prefix+'clinics/c-b'},'c-b',''),('C',{'mapValue':{'fields':{'id':sv('c-c'),'meta':sv('extra')}}},'c-c','c-c'),('D',sv('absent'),None,'Unlinked'),('E',sv(' c-a '),None,'Unlinked'),('F',{'referenceValue':'projects/demo-other/databases/(default)/documents/clinics/c-a'},None,'Unlinked'),('G',{'referenceValue':prefix+'providers/c-a'},None,'Unlinked'),('H',{'nullValue':None},None,'Unlinked'),('I',{'mapValue':{'fields':{'id':{'integerValue':'2'}}}},None,'Unlinked'),('J',None,None,'Unlinked')]
        expected=[]
        for ident,relation,target,label in forms:
            fields={'name':sv('Provider '+ident)}
            if relation is not None:fields['clinic']=relation
            seed['providers/'+ident]=fields;expected.append({'id':ident,'name':'Provider '+ident,'relation_id':target,'relation_name':label})
        seed['bookings/a']={'provider':{'referenceValue':prefix+'providers/A'}}
        seed['bookings/b']={'name':sv(''),'provider':{'mapValue':{'fields':{'id':sv('B')}}}}
        seed['bookings/c']={'name':sv('Dangling booking'),'provider':sv('absent')}
        service['seed'](origin,seed);before=snapshot(service,origin,seed)
        rows=run([{'op':'view','collection':'providers'},{'op':'view','collection':'bookings'},{'op':'view','collection':'clinics'}],origin,'compatibility')
        keys=['id','name','relation_id','relation_name']
        project=lambda row:[{k:item[k] for k in keys} for item in value(row)]
        assert project(rows[0])==expected
        assert project(rows[1])==[{'id':'a','name':'a','relation_id':'A','relation_name':'Provider A'},{'id':'b','name':'','relation_id':'B','relation_name':'Provider B'},{'id':'c','name':'Dangling booking','relation_id':None,'relation_name':'Unlinked'}]
        assert project(rows[2])==[{'id':'c-a','name':'<b>Literal Clinic</b>','relation_id':None,'relation_name':None},{'id':'c-b','name':'','relation_id':None,'relation_name':None},{'id':'c-c','name':'c-c','relation_id':None,'relation_name':None}]
        assert snapshot(service,origin,seed)==before


def migration():
    with isolated_database() as (service,origin):
        prefix='projects/demo-sweclar/databases/(default)/documents/'
        seed={'clinics/c-a':{'name':sv('Clinic')},'bookings/keep':{'nested':{'mapValue':{'fields':{'a':{'integerValue':'9'}}}}}}
        for i in range(61):
            relation={'referenceValue':prefix+'clinics/c-a'} if i%2 else {'mapValue':{'fields':{'id':sv('c-a')}}}
            seed[f'providers/p-{i:02}']={'name':sv('Provider '+str(i)),'clinic':relation,'array':{'arrayValue':{'values':[sv('preserved'),{'booleanValue':False}]}},'stamp':{'timestampValue':'2001-01-01T00:00:00Z'}}
        for name,value_ in [('dangling',sv('absent')),('null',{'nullValue':None}),('wrong',{'referenceValue':prefix+'bookings/keep'})]:seed['providers/'+name]={'clinic':value_,'keep':sv('unchanged')}
        seed['providers/normalized']={'clinic':sv('c-a'),'keep':sv('stable')};seed['providers/missing']={'keep':sv('no field')}
        service['seed'](origin,seed);before=snapshot(service,origin,seed)
        expected=copy.deepcopy(seed)
        for i in range(61):expected[f'providers/p-{i:02}']['clinic']=sv('c-a')
        for name in ['dangling','null','wrong']:del expected['providers/'+name]['clinic']
        op={'op':'normalize','collection':'providers','field':'clinic','target':'clinics'}
        with proxy(service,origin) as (base,requests):rows=run([op,op],base,'migration')
        assert [{k:r[k] for k in ['document','field','reason']} for r in value(rows[0])]==[{'document':x,'field':'clinic','reason':'dangling_relation'} for x in ['dangling','null','wrong']]
        assert value(rows[1])==[]
        assert {p:get(service,origin,p)['fields'] for p in seed}==expected
        assert len([r for r in requests if r['method']=='POST'])==1
        for path in ['providers/normalized','providers/missing','bookings/keep','clinics/c-a']:assert get(service,origin,path)==before[path]
        # Reset the source records, then introduce a real concurrent write immediately before commit.
        service['seed'](origin,seed);before=snapshot(service,origin,seed);injected=[]
        def edit():
            if injected:return
            fields=copy.deepcopy(seed['providers/p-00']);fields['concurrent']=sv('must survive')
            service['seed'](origin,{'providers/p-00':fields});injected.append(True)
        with proxy(service,origin,edit) as (base,requests):rows=run([op],base,'concurrent-migration')
        assert injected and 'candidate_error' in rows[0]
        assert get(service,origin,'providers/p-00')['fields']=={**seed['providers/p-00'],'concurrent':sv('must survive')}
        for path in seed:
            if path!='providers/p-00':assert get(service,origin,path)==before[path]
        assert len([r for r in requests if r['method']=='POST'])==1,'Concurrent edit must not trigger a silent retry'


def workflow():
    with isolated_database() as (service,origin):
        seed={'clinics/c':{'name':sv('Clinic')},'providers/p':{'name':sv('Provider'),'clinic':{'mapValue':{'fields':{'id':sv('c')}}}},'providers/d':{'name':sv('Unlinked provider'),'clinic':sv('absent')},'bookings/b':{'name':sv('Keep selected page'),'provider':sv('p')}}
        service['seed'](origin,seed)
        operations=[{'op':'mount'},{'op':'tap','key':'nav-providers'},{'op':'hold','method':'POST'},{'op':'tap','key':'repair'},{'op':'tap','key':'repair'},{'op':'tap','key':'nav-bookings'},{'op':'release'},{'op':'tap','key':'repair'}]
        with proxy(service,origin) as (base,requests):rows=run(operations,base,'workflow')
        assert text(rows[3],'repair-state')==['pending'] and text(rows[3],'repair-progress')
        assert rows[3]['requests']==rows[4]['requests'], 'A repeated pending repair triggered another request'
        assert text(rows[4],'repair-state')==['pending']
        assert text(rows[6],'page-title')==['bookings'] and 'Keep selected page' in rows[6]['texts']
        assert text(rows[6],'repair-state')==['success'] and text(rows[6],'repair-count')==['1']
        assert text(rows[7],'repair-state')==['success'] and text(rows[7],'repair-count')==['0']
        assert len([r for r in requests if r['method']=='POST'])==1
        assert get(service,origin,'providers/p')['fields']['clinic']==sv('c') and 'clinic' not in get(service,origin,'providers/d')['fields']
        service['seed'](origin,seed);before=snapshot(service,origin,seed)
        rows=run([{'op':'mount'},{'op':'tap','key':'nav-providers'},{'op':'fail','method':'POST'},{'op':'tap','key':'repair'},{'op':'capture','name':'failure.png'}],origin,'workflow-failure')
        assert text(rows[3],'repair-state')==['error'] and text(rows[3],'repair-count') is None
        assert snapshot(service,origin,seed)==before
        retry=run([{'op':'mount'},{'op':'fail','method':'POST'},{'op':'tap','key':'repair'},{'op':'fail','method':None},{'op':'tap','key':'repair'}],origin,'workflow-commit-retry')
        assert text(retry[2],'repair-state')==['error'] and text(retry[4],'repair-state')==['success']
        service['seed'](origin,seed)
        rows=run([{'op':'mount'},{'op':'fail','method':'GET'},{'op':'tap','key':'repair'},{'op':'fail','method':None},{'op':'tap','key':'repair'}],origin,'workflow-retry')
        assert text(rows[2],'repair-state')==['error']
        assert text(rows[4],'repair-state')==['success'] and text(rows[4],'repair-count')==['1']
        service['seed'](origin,seed)
        with proxy(service,origin,fail_first_reload=True) as (base,requests):
            rows=run([{'op':'mount'},{'op':'tap','key':'nav-providers'},{'op':'tap','key':'repair'},{'op':'tap','key':'repair'}],base,'workflow-post-commit-reload')
        assert text(rows[2],'repair-state')==['error'] and text(rows[2],'repair-count') is None
        # The next actual tap must complete successfully; widget class is free.
        assert text(rows[3],'repair-state')==['success'] and text(rows[3],'repair-count')==['0']
        assert get(service,origin,'providers/p')['fields']['clinic']==sv('c')
        assert 'clinic' not in get(service,origin,'providers/d')['fields']


def main():
    checks=[core,screens,compatibility,migration,workflow];results=[];infra=[]
    selected=os.environ.get('MAINTENANCE_GATE')
    for i,check in enumerate(checks,1):
        if selected and int(selected)!=i:continue
        try:check();results.append({'ru_id':f'RU-{i:03}','passed':True})
        except (AssertionError,KeyError,TypeError) as error:
            results.append({'ru_id':f'RU-{i:03}','passed':False,'detail':str(error) or type(error).__name__})
            (LOG/(f'gate-{i}-failure.log')).write_text(traceback.format_exc());print(traceback.format_exc(),file=sys.stderr)
        except Exception as error:
            infra.append({'gate':i,'error':str(error)});(LOG/(f'gate-{i}-infrastructure.log')).write_text(traceback.format_exc());print(traceback.format_exc(),file=sys.stderr)
    print(json.dumps({'harness_ok':not infra,'results':results,'infrastructure_errors':infra}))
    return 0 if not infra else 2

if __name__=='__main__':raise SystemExit(main())
