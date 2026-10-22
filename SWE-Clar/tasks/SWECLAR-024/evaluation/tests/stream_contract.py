"""Five retained RU checks. Environment preparation is an independent prerequisite."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

TESTS=Path(__file__).resolve().parent
PUBLIC=Path(os.environ.get('STREAM_PUBLIC_TESTS','/public_tests'))
sys.path.insert(0,str(TESTS))
sys.path.insert(0,str(PUBLIC))
from stream_support import Application,identity
from media_content_checks import make_fixture,inspect_content,FF,FP
from publisher_contract import invalid_publisher_url

CONFIG={'admin_token':'demo-admin','stream_keys':{'alpha':'demo-alpha','beta':'demo-beta','gamma':'demo-gamma'}}

class Client:
    def __init__(self,app):
        self.app=app
        self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(self,path,body=None,status=200,admin=False,headers=None,raw=False):
        h={'Content-Type':'application/json',**(headers or {})}
        if admin:h['Authorization']='Bearer demo-admin'
        req=urllib.request.Request(self.app.url+path,data=json.dumps(body).encode() if body is not None else None,headers=h)
        try:r=self.http.open(req,timeout=25)
        except urllib.error.HTTPError as error:r=error
        with r:
            data=r.read()
            accepted=status if isinstance(status,(tuple,list,set,frozenset)) else (status,)
            assert r.status in accepted,(path,r.status,data[:200])
            return data if raw else json.loads(data)

def event(c,ident='alpha',**extra):
    return c.request('/event',{'event_id':ident,'title':'Synthetic recording','start':'2035-01-01T00:00:00Z','end':'2035-01-01T01:00:00Z',**extra},admin=True)

def publish(c):return c.request('/publish',{'event_id':'alpha','terms':['synthetic-index']},admin=True)

def record(c,temporary,live_check=False):
    event(c)
    urls=c.request('/start',{'event_id':'alpha','stream_key':'demo-alpha'},admin=True)
    fixture=make_fixture(temporary/'source.mp4',731)
    broadcaster=sp.Popen([FF,'-nostdin','-v','error','-re','-i',str(temporary/'source.mp4'),'-c','copy','-f','flv',urls['ingest_url']],stdout=sp.PIPE,stderr=sp.PIPE)
    try:
        if live_check:
            deadline=time.monotonic()+8
            while True:
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urls['hls_url'],timeout=2) as response:
                        assert b'#EXTM3U' in response.read()
                    break
                except Exception:
                    if time.monotonic()>deadline:raise
                    time.sleep(.1)
            live=sp.run([FF,'-nostdin','-v','error','-i',urls['hls_url'],'-t','1','-an','-vf','scale=16:16','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],capture_output=True,timeout=15)
            assert live.returncode==0 and len(live.stdout)>=16*16*3*5,'HLS did not deliver actual frames'
        _,err=broadcaster.communicate(timeout=15)
        assert broadcaster.returncode==0,err[-300:]
    finally:
        if broadcaster.poll() is None:broadcaster.kill();broadcaster.communicate()
    metadata=c.request('/end',{'event_id':'alpha'},admin=True)
    assert not any(k in metadata for k in ['path','media_root','admin_token','stream_key'])
    return fixture,metadata

def browser(app,count=False):
    env=dict(os.environ,STREAM_BROWSER_HOME=str(app.project/'runtime'),STREAM_BROWSER_WRAPPER=str(PUBLIC/'browser_launch.py'))
    result=sp.run([os.environ.get('NODE_BIN','node'),str(TESTS/'browser_check.cjs'),app.url,'count' if count else 'play'],env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr[-1200:]
    return json.loads(result.stdout)

def ru001(app,c,temp):
    assert b'<html' in c.request('/',raw=True)
    for path in ['/store.py','/config.json','/media/alpha']:
        c.request(path,status=404)
    c.request('/event',{},status=403)
    assert c.request('/calendar?now=2034-01-01T00:00:00Z')==[]

def ru002(app,c,temp):
    event(c,'beta');event(c,'alpha',start='2035-01-01T08:00:00+08:00')
    assert [x['event_id'] for x in c.request('/calendar?now=2035-01-01T00:00:00Z')]==['alpha','beta']
    c.request('/cancel',{'event_id':'alpha'},admin=True)
    assert [x['event_id'] for x in c.request('/calendar?now=2035-01-01T00:00:00Z')]==['beta']
    assert c.request('/calendar?now=2035-01-01T00:00:00.001Z')==[]
    baseline=c.request('/calendar?now=2034-01-01T00:00:00Z')
    valid={'event_id':'gamma','title':'Valid synthetic event','start':'2035-01-01T00:00:00Z','end':'2035-01-01T01:00:00Z'}
    for changes in [{'title':'   '},{'start':'2035-01-01T00:00:00'},
                    {'end':'2035-01-01T00:00:00Z'},{'end':'2034-12-31T23:00:00Z'},
                    {'event_id':'../unconfigured'}]:
        c.request('/event',{**valid,**changes},admin=True,status=400)
        assert c.request('/calendar?now=2034-01-01T00:00:00Z')==baseline,'Invalid event changed calendar state'
    c.request('/event',valid,admin=True)
    c.request('/event',{**valid,'title':'Duplicate must not replace'},admin=True,status=400)
    rows=c.request('/calendar?now=2034-01-01T00:00:00Z')
    assert next(x for x in rows if x['event_id']=='gamma')['title']==valid['title']

def ru003(app,c,temp):
    event(c,'beta')
    c.request('/end',{'event_id':'beta'},admin=True,status=400)
    c.request('/start',{'event_id':'beta','stream_key':'wrong'},admin=True,status=400)
    urls=c.request('/start',{'event_id':'beta','stream_key':'demo-beta'},admin=True)
    c.request('/start',{'event_id':'beta','stream_key':'demo-beta'},admin=True,status=400)
    wrong=invalid_publisher_url(urls['ingest_url'],'demo-beta')
    bad=sp.run([FF,'-nostdin','-v','error','-f','lavfi','-i','color=red:s=64x64:r=10:d=1','-c:v','libx264','-f','flv',wrong],capture_output=True,timeout=10)
    assert bad.returncode!=0,'RTMP accepted a wrong publisher secret'
    c.request('/end',{'event_id':'beta'},admin=True,status=400)
    # The public contract requires rejection of a missing/failed archive but
    # deliberately does not prescribe whether that is reported as bad input
    # (400) or a missing resource (404).
    c.request('/publish',{'event_id':'beta','terms':['synthetic']},admin=True,status=(400,404))
    record(c,temp,live_check=True)

def ru004(app,c,temp):
    fixture,metadata=record(c,temp)
    assert c.request('/archives')==[]
    c.request('/media/alpha',status=404)
    c.request('/publish',{'event_id':'alpha','terms':[]},admin=True,status=400)
    publish(c)
    rows=c.request('/archives?q=SYNTHETIC-INDEX&start=2035-01-01T00:00:00Z&end=2035-01-02T00:00:00Z')
    assert len(rows)==1 and rows[0]['event_id']=='alpha'
    assert c.request('/archives?end=2035-01-01T00:00:00Z')==[]
    raw=c.request('/media/alpha',raw=True)
    assert len(raw)==metadata['bytes'] and hashlib.sha256(raw).hexdigest()==metadata['sha256']
    assert c.request('/media/alpha',headers={'Range':'bytes=10-29'},status=206,raw=True)==raw[10:30]
    downloaded=temp/'download.mp4';downloaded.write_bytes(raw)
    observed=inspect_content(downloaded,fixture)
    assert abs(observed['duration']-metadata['duration'])<.15
    assert observed['frames']==metadata['frames'],'Reported frame count differs from actual recording'
    browser(app)
    app.stop();app.start();fresh=Client(app)
    assert fresh.request('/media/alpha',raw=True)==raw
    assert len(fresh.request('/archives'))==1
    app.stop()
    archive_storage_faults()

def archive_storage_faults():
    # Public storage interface: regular finalized MP4 beneath configured media_root.
    # Discover by measured content, never private names, paths or database schema.
    for fault in ['changed','missing']:
        with tempfile.TemporaryDirectory(prefix='stream-storage-oracle-') as directory:
            with Application(config=CONFIG) as app:
                client=Client(app)
                _,metadata=record(client,Path(directory))
                code="""import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]);digest=sys.argv[2];mode=sys.argv[3]
files=[f for f in root.rglob('*') if f.is_file() and hashlib.sha256(f.read_bytes()).hexdigest()==digest]
assert files,'Finalized media file absent from declared media_root'
for f in files:
 if mode=='missing':f.unlink()
 else:
  raw=bytearray(f.read_bytes());raw[len(raw)//2]^=1;f.write_bytes(raw)
print(json.dumps({'affected':len(files)}))
"""
                altered=json.loads(sp.check_output([sys.executable,'-I','-c',code,app.config['media_root'],metadata['sha256'],fault],text=True,**identity()))
                assert altered['affected']>0
                client.request('/publish',{'event_id':'alpha','terms':['synthetic-index']},admin=True,status=400)
                assert client.request('/archives')==[]
                client.request('/media/alpha',status=404)

def ru005(app,c,temp):
    record(c,temp)
    body={'event_id':'alpha','viewer_id':'invented','session_id':'invented'}
    # Private recordings must never count; the contract leaves the 400/404
    # representation of that rejected lookup open.
    c.request('/view',body,status=(400,404))
    publish(c)
    c.request('/',raw=True)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:c.request('/view',body)['views'],range(6)))
    assert results==[1]*6
    second=Client(app)
    assert second.request('/view',body)['views']==2
    assert c.request('/view',{**body,'viewer_id':'changed'})['views']==2
    c.request('/view',{'event_id':'missing'},status=(400,404))
    browser(app,count=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--gates',default='1,2,3,4,5');args=parser.parse_args()
    selected=[int(x) for x in args.gates.split(',')]
    assert selected and all(1<=i<=5 for i in selected)
    missing=[]
    if any(i>=3 for i in selected):
        missing=[name for name in [FF,FP,os.environ.get('MEDIAMTX_BIN','mediamtx')] if not shutil.which(name)]
    if any(i>=4 for i in selected) and not shutil.which(os.environ.get('NODE_BIN','node')):missing.append('prepared browser driver')
    if missing:return {'harness_ok':False,'infrastructure_errors':['Missing prepared tools: '+', '.join(missing)],'results':[]}
    rows=[]
    for i in selected:
        try:
            with tempfile.TemporaryDirectory(prefix='stream-oracle-') as directory:
                with Application(config=CONFIG) as app:
                    globals()[f'ru{i:03d}'](app,Client(app),Path(directory))
            rows.append({'ru_id':f'RU-{i:03d}','passed':True})
        except Exception as error:
            rows.append({'ru_id':f'RU-{i:03d}','passed':False,'detail':str(error),'trace':traceback.format_exc()[-1600:]})
    return {'harness_ok':True,'selected_gates':selected,'results':rows}

if __name__=='__main__':print(json.dumps(main()))
