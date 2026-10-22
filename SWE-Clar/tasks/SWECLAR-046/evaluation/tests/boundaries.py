import json,os,subprocess,sys,uuid,shutil,tempfile
from pathlib import Path
from test_solution import provider,run
from conftest import load_solution

def ru001():
    # Run the unchanged console in an isolated copy with evaluator-owned demo input.
    sandbox=tempfile.TemporaryDirectory(prefix='pipeline-console-')
    Path(sandbox.name).chmod(0o755)
    root=Path(sandbox.name)/'project'
    shutil.copytree(Path(os.environ['CANDIDATE_ROOT']),root)
    (root/'source.json').write_text(json.dumps([{'source_id':'sample-row','name':'Protected fixture','email':'contact@example.test'}]))
    database='/tmp/pipeline-'+uuid.uuid4().hex+'.db'
    def worker(args,**kwargs):
        p=subprocess.run(args,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=15,**kwargs)
        assert p.returncode==0,p.stderr[-800:]
        return p.stdout
    def console(state,event):return json.loads(worker([sys.executable,str(root/'cli.py'),'--database',database],input=json.dumps({'state':state,'event':event})))
    try:
        state=console({}, {'type':'sync','source':'source','destination':'destination'})
        assert state['result']['created']==1
        state=console(state,{'type':'queue_outreach','destination':'destination','source_id':'sample-row','channel':'email'})
        assert state['result']['updated']==1
        again=console(state,{'type':'queue_outreach','destination':'destination','source_id':'sample-row','channel':'email'})
        assert again['result']['skipped']==1
        code='import sqlite3,json,sys;d=sqlite3.connect(sys.argv[1]);print(json.dumps({t:[json.loads(r[0]) for r in d.execute("SELECT body FROM "+t)] for t in ["destination","deliveries"]}))'
        result=json.loads(worker([sys.executable,'-c',code,database]))
        assert result['destination'][0]['status']=='queued' and len(result['deliveries'])==1
        assert result['deliveries'][0]['email']=='contact@example.test'
    finally:
        try:worker([sys.executable,'-c','from pathlib import Path;import sys;Path(sys.argv[1]).unlink(missing_ok=True)',database])
        finally:sandbox.cleanup()

def ru002():
    m=load_solution()
    # IDs are opaque strings; no trimming policy was specified. Do not make
    # failure injection depend on an undeclared whitespace normalization.
    with provider([{'source_id':'bad','name':'One'},{'source_id':0,'name':'Two'},{'source_id':False},{'source_id':''},{'source_id':1.2}]) as (client,rows,target,requests,deliveries,fail,secret):
        fail['put'].add('bad');out=run(m,{},client)
        assert out['result']['processed']==5 and out['result']['created']==1 and out['result']['failed']==4
        assert set(target)=={'0'}
    with provider([]) as (client,rows,target,requests,deliveries,fail,secret):
        out=run(m,{},client);assert out['result']['processed']==0 and out['result']['failed']==0

def ru003():
    m=load_solution();owned={'status':'queued','assignee':'','notes':None,'first_contact_date':'','estimated_students':0,'annual_license_value':0}
    with provider([{'source_id':'x','name':'Revised','status':'new'}],{'x':{'source_id':'x','name':'Old','extra':{'keep':1},**owned}}) as (client,rows,target,requests,deliveries,fail,secret):
        run(m,{},client)
        for key,value in owned.items():assert target['x'][key]==value
        assert target['x']['extra']=={'keep':1} and target['x']['name']=='Revised'

def linkedin_guard(m,client,target,requests,deliveries):
    skipped=run(m,{},client,'queue_outreach',source_id='x',channel='linkedin')
    assert skipped['result']['skipped']==1 and target['x']['status']=='new' and not deliveries
    assert not any(r[0] in ('POST','PUT') for r in requests)

def ru004():
    m=load_solution()
    with provider(destination={'x':{'source_id':'x','email':'synthetic@example.test','status':'new'}}) as (client,rows,target,requests,deliveries,fail,secret):
        linkedin_guard(m,client,target,requests,deliveries)
        fail['outreach_ack']=True;out=run(m,{},client,'queue_outreach',source_id='x',channel='email')
        assert out['result']['failed']==1 and not out['outbox'] and target['x']['status']=='new'
        assert not any(r[0]=='PUT' for r in requests)
        fail['outreach_ack']=False;out=run(m,out,client,'queue_outreach',source_id='x',channel='email')
        assert len(deliveries)==1 and target['x']['status']=='queued'

def ru005():
    m=load_solution();keys=['token','secret','credential','credentials','webhook_url','api_key','connection','private_connection','password','authorization','access_token','refresh_token','client_secret']
    payload={f' {key.upper()} ':'synthetic-credential-marker' for key in keys}
    with provider([{'source_id':'x','nested':[payload,{'keep':1}]}]) as (client,rows,target,requests,deliveries,fail,secret):
        out=run(m,{'nested':[payload]},client)
        assert 'synthetic-credential-marker' not in json.dumps([out,target])
        assert target['x']['nested']==[{}, {'keep':1}]
        rows[:]=[{'source_id':'x'}];target['invalid']=[]
        before=len(requests);bad=run(m,out,client)
        assert bad['error']['code']=='service_failed' and not bad.get('result')
        assert not any(r[0]=='PUT' for r in requests[before:])
