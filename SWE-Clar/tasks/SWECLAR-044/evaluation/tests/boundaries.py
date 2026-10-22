import csv,io,math,os,json,subprocess,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from pathlib import Path
from candidate_proxy import call

def base():return {'categories':{'a':{},'b':{}},'trends':{},'meta':{'keep':[1,2]}}
def ingest(state,rows,category='a'):
    out=io.StringIO();w=csv.writer(out);w.writerow(['trend_id','keyword','month','count']);w.writerows(rows)
    return raw(state,out.getvalue(),category)
def raw(state,text,category='a'):return call(state,{'type':'sync_source','category_id':category,'url':'http://source.example.test/fixture.csv'},fetch_text=lambda _:text)
def err(value):assert isinstance(value.get('error',{}).get('code'),str) and value['error']['code'].strip()

def ru001():
    good=raw(base(),'\ufeffcount,keyword,month,trend_id\n125,"Tools, garden",2030-02,t\n100,"Tools, garden",2030-01,t\n')
    assert good['trends']['t']['growth']==25 and good['trends']['t']['keyword']=='Tools, garden'
    for text in ['trend_id,keyword,month,count\nt,x,2030-01,1,extra\n','trend_id,keyword,month,count\nt,x,2030-01\n','trend_id,keyword,month,count\nt,x,0000-01,1\n','trend_id,keyword,month,count\nt,x,2030-01,inf\n','trend_id,keyword,month,count\nt,x,2030-01,1\nt,y,2030-02,2\n','trend_id,keyword,month,count\n,x,2030-01,1\n','trend_id,keyword,month,count\nt,  ,2030-01,1\n','trend_id,keyword,month,count\nt,"unterminated,2030-01,1\n']:
        result=raw(good,text);assert result['error']['code']=='invalid_source';assert result['trends']==good['trends'] and result['meta']==good['meta']
    assert raw(good,'trend_id,keyword,month,count\n')['trends']==good['trends']
    conflict=ingest(good,[('t','Tools, garden','2030-03',150)],'b');assert conflict['error']['code']=='invalid_source'
    root=Path(os.environ['CANDIDATE_ROOT'])
    class Source(BaseHTTPRequestHandler):
        def do_GET(self):
            body=b'trend_id,keyword,month,count\nconsole,Fixture,2030-01,100\nconsole,Fixture,2030-02,150\n'
            self.send_response(200);self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Source);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        request={'state':base(),'action':{'type':'sync_source','category_id':'a','url':f'http://127.0.0.1:{server.server_port}/measurements.csv'}}
        p=subprocess.run([sys.executable,str(root/'cli.py')],input=json.dumps(request),capture_output=True,text=True,timeout=15,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
    finally:server.shutdown();server.server_close();thread.join()
    assert p.returncode==0,p.stderr
    result=json.loads(p.stdout);assert result['trends']['console']['growth']==50

def ru002():
    state=ingest(base(),[('t','Test','2030-03',300),('t','Test','2030-01',100),('t','Test','2030-02',200)])
    assert state['trends']['t']['growth']==50
    state['trends']['t']['custom']={'keep':True}
    state=ingest(state,[('t','Test','2030-02',240)])
    assert state['trends']['t']['growth']==25 and state['trends']['t']['custom']=={'keep':True}
    history=state['trends']['t']['history'];assert len(history)==3 and history[1]['count']==240
    for value,growth,label in [(115,15,'rising'),(130,30,'rising'),(130.001,30.001,'hot'),(0,-100,'declining')]:
        row=ingest(base(),[('t','T','2030-01',100),('t','T','2030-02',value)])['trends']['t']
        assert math.isclose(row['growth'],growth,abs_tol=1e-8) and row['classification']==label

def ru003():
    state=base()
    for tid,word,growth,category in [('z','Alpha',20,'a'),('a','alpha',20,'a'),('b','Beta',20,'a'),('n','Negative',-10,'a'),('hidden','Other',200,'b')]:
        state=ingest(state,[(tid,word,'2030-01',100),(tid,word,'2030-02',100+growth)],category)
    state=ingest(state,[('u','Unknown','2030-01',0)])
    state['trends']['a']['custom']={'keep':[1,2]}
    result=call(state,{'type':'category_view','category_ids':['a']})
    assert [r['trend_id'] for r in result['result']['trends']]==['a','z','b','n','u']
    for row in result['result']['trends']:
        for key,value in state['trends'][row['trend_id']].items():assert row[key]==value
    for selection in [[],['a','b'],['a','a'],['missing']]:err(call(state,{'type':'category_view','category_ids':selection}))

def ru004():
    state=ingest(base(),[('t','T','2030-01',1),('u','U','2030-01',1)])
    for user,tid in [('one','t'),('two','u'),('one','u'),('one','t')]:state=call(state,{'type':'watch','user_id':user,'trend_id':tid})
    assert state['watchlists']['one']==['t','u'] and state['watchlists']['two']==['u']
    state=call(state,{'type':'unwatch','user_id':'one','trend_id':'t'})
    assert state['watchlists']['one']==['u'] and state['watchlists']['two']==['u']
    err(call(state,{'type':'watch','user_id':'one','trend_id':'missing'}))
    state['suggestions']={'seed':[' First phrase ','FIRST PHRASE','Second phrase','']}
    assert call(state,{'type':'discover','seed':' SEED '})['result']['suggestions']==['First phrase','Second phrase']
    assert call(state,{'type':'discover','seed':'unknown'})['result']['suggestions']==[]

def ru005():
    state=base();action={'type':'generate_keywords','category_id':'a','month':'2030-01','candidates':[' ','New','NEW',None,5,'second']}
    state=call(state,action);ids=state['result']['added_ids']
    assert len(ids)==2 and [state['trends'][i]['keyword'] for i in ids]==['New','second']
    for i in ids:assert state['trends'][i]['history']==[] and state['trends'][i]['growth'] is None
    err(call(state,action))
    state=call(state,{**action,'category_id':'b'});assert len(state['result']['added_ids'])==2
    state=call(state,{**action,'month':'2030-02'});assert state['result']['added_ids']==[]
    err(call(state,{**action,'month':'2030-02','candidates':['third']}))
