"""Independent HTTP observations; never import candidate modules in the evaluator."""
import json,sys,os,sqlite3,tempfile,subprocess,socket
from pathlib import Path
sys.path.insert(0,str(Path('/public_tests') if Path('/public_tests/control_support.py').is_file() else Path(__file__).resolve().parents[2]/'public_tests'))
from control_support import Application,identity

def seed(linked=True):
    return {'users':{'pa':{'role':'parent'},'ca':{'role':'child','parent_id':'pa'},'pb':{'role':'parent'},'cb':{'role':'child','parent_id':'pb'}},'devices':({'da':{'mode':'parent_child','owner_id':'ca','parent_id':'pa'},'db':{'mode':'parent_child','owner_id':'cb','parent_id':'pb'}} if linked else {}),'policies':{},'activity':[],'notifications':[],'audit':[]}

def policy():return {'blocked_domains':['blocked.test'],'blocked_apps':['chat'],'app_daily_limits':{'video':30}}
def act(app,**kw):return app.request('/action',kw)

def check(n):
    s=seed(n!=2)
    if n==4:s['policies']['da']=policy()
    if n==5:
        s['policies']={'da':policy(),'db':policy()}
        s['activity']=[{'event_id':'a','device_id':'da'},{'event_id':'b','device_id':'db'}]
        s['notifications']=[{'device_id':'da','parent_id':'pa'},{'device_id':'db','parent_id':'pb'}]
        s['audit']=[{'subject':'pa','type':'old'},{'subject':'pb','type':'old'}]
    with Application(s) as app:
        if n==1:
            probe="import copy,json;from policy import process_control_action as f;s="+repr(seed(False))+";a={'type':'configure_mode','mode':'self','user_id':'pa','device_id':'self'};old=copy.deepcopy((s,a));f(s,a);assert (s,a)==old"
            subprocess.run([sys.executable,'-c',probe],cwd=app.project,check=True,**identity())
            assert app.request('/state')['users']==s['users']
            r=act(app,type='configure_mode',user_id='pa',device_id='self',mode='self');assert r['devices']['self']['owner_id']=='pa'
            app.restart();assert app.request('/state')['devices']['self']['owner_id']=='pa'
        elif n==2:
            args=dict(type='configure_mode',user_id='pa',child_id='ca',device_id='da',mode='parent_child')
            r=act(app,**args);assert r['devices']['da']['parent_id']=='pa' and r['devices']['da']['owner_id']=='ca'
            for change in ({},{'device_id':'duplicate'},{'device_id':'cross','user_id':'pb'}):
                assert act(app,**{**args,**change})['error']['code']=='link_denied'
            assert act(app,type='configure_mode',user_id='pa',child_id='cb',device_id='cross-new',mode='parent_child')['error']['code']=='link_denied'
            assert list(app.request('/state')['devices'])==['da']
        elif n==3:
            # Self-protection owners are authorized too; parent-only controls
            # cannot establish the whole policy authorization requirement.
            assert 'error' not in act(app,type='configure_mode',user_id='pa',device_id='self',mode='self')
            assert 'error' not in act(app,type='set_policy',actor_id='pa',device_id='self',**policy())
            own_before=app.request('/state')
            assert act(app,type='set_policy',actor_id='pb',device_id='self',**policy())['error']['code']=='policy_denied'
            assert app.request('/state')==own_before
            app.restart()
            assert act(app,type='check_access',device_id='self',event_id='self-blocked',target_type='app',target='chat')['result']['allowed'] is False
            assert act(app,type='check_access',device_id='da',event_id='before-policy',target_type='app',target='chat')['result']['allowed'] is True
            assert 'error' not in act(app,type='set_policy',actor_id='pa',device_id='da',**policy())
            for i,(target,allowed) in enumerate([('BLOCKED.TEST.',False),('a.blocked.test',False),('notblocked.test',True),('blocked.test.evil',True)]):
                assert act(app,type='check_access',device_id='da',event_id=str(i),target_type='domain',target=target)['result']['allowed'] is allowed
            for i,(target,usage,allowed) in enumerate([('chat',0,False),('video',29.9,True),('video',30,False),('other',999,True)]):
                assert act(app,type='check_access',device_id='da',event_id='app'+str(i),target_type='app',target=target,used_minutes=usage)['result']['allowed'] is allowed
            before=app.request('/state')
            assert act(app,type='set_policy',actor_id='pb',device_id='da',**policy())['error']['code']=='policy_denied'
            assert act(app,type='set_policy',actor_id='pa',device_id='da',**{**policy(),'app_daily_limits':{'x':-1}})['error']['code']=='invalid_policy'
            assert app.request('/state')==before
            replacement=dict(blocked_domains=['replacement.test'],blocked_apps=['new-app'],app_daily_limits={'reader':5})
            assert 'error' not in act(app,type='set_policy',actor_id='pa',device_id='da',**replacement)
            app.restart()
            for i,(kind,target,usage,allowed) in enumerate([('domain','blocked.test',0,True),('app','chat',0,True),('app','video',100,True),('domain','a.replacement.test',0,False),('app','new-app',0,False),('app','reader',5,False),('app','reader',4,True)]):
                assert act(app,type='check_access',device_id='da',event_id='replacement-'+str(i),target_type=kind,target=target,used_minutes=usage)['result']['allowed'] is allowed
            assert 'error' not in act(app,type='set_policy',actor_id='pa',device_id='da',blocked_domains=[],blocked_apps=[],app_daily_limits={})
            app.restart();assert act(app,type='check_access',device_id='da',event_id='fresh',target_type='app',target='chat')['result']['allowed'] is True
        elif n==4:
            args=dict(type='check_access',device_id='da',event_id='retry',target_type='app',target='chat')
            act(app,**args);act(app,**args);app.restart()
            r=app.request('/state');assert len(r['activity'])==1 and len(r['notifications'])==1
            assert r['notifications'][0]['parent_id']=='pa' and r['notifications'][0]['event_id']=='retry'
            assert act(app,**{**args,'target':'video'})['error']['code']=='event_conflict'
            assert act(app,type='report',parent_id='pa',device_id='da')['result']['activity']==r['activity']
            assert act(app,type='report',parent_id='pb',device_id='da')['error']['code']=='report_denied'
            assert act(app,type='report',parent_id='pb',device_id='db')['result']['activity']==[]
        elif n==5:
            act(app,type='delete_account',user_id='pa');app.restart();r=app.request('/state')
            assert 'pa' not in r['users'] and 'parent_id' not in r['users']['ca']
            assert 'da' not in r['devices'] and 'da' not in r['policies']
            assert r['devices']['db']==s['devices']['db'] and r['policies']['db']==s['policies']['db']
            assert r['activity']==[s['activity'][1]] and r['notifications']==[s['notifications'][1]]
            assert not any(e.get('subject')=='pa' for e in r['audit'])
            assert r['audit'][-1].get('type')=='account_deleted' and r['audit'][-1].get('subject')=='redacted'
            assert s['audit'][1] in r['audit']
            assert act(app,type='delete_account',user_id='pa')['error']['code']=='account_missing'

def main():
    try:
        with tempfile.TemporaryDirectory() as td:
            with sqlite3.connect(str(Path(td)/'health.db')) as db:
                db.execute('create table x(v integer)');db.execute('insert into x values(17)')
            with sqlite3.connect(str(Path(td)/'health.db')) as db:assert db.execute('select v from x').fetchone()==(17,)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0))
        p=subprocess.run([sys.executable,'-I','-c','import os;assert os.geteuid()!=0'],check=True,**identity())
    except Exception as e:
        print(json.dumps({'harness_ok':False,'infrastructure_errors':[str(e)],'results':[]}));return 2
    results=[]
    for n in range(1,6):
        try:check(n);results.append({'ru_id':f'RU-{n:03}','passed':True})
        except Exception as e:results.append({'ru_id':f'RU-{n:03}','passed':False,'detail':type(e).__name__+': '+str(e)})
    print(json.dumps({'harness_ok':True,'results':results}));return 0

if __name__=='__main__':
    raise SystemExit(main())
