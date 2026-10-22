"""Existing real HTTP authentication, registration and scoped-list regression."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,select,urllib.request,urllib.error
from importlib.metadata import version
assert version('Pillow')=='12.3.0'
identities=json.loads(Path('runtime/identities.json').read_text())
review=next(k for k,v in identities.items() if v['role']=='review');supplier=next(k for k,v in identities.items() if v['role']=='supplier');sid=identities[supplier]['supplier_id']
with tempfile.TemporaryDirectory() as temp:
    process=subprocess.Popen([sys.executable,'server.py'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={**os.environ,'PORT':'0','DATABASE_PATH':temp+'/db.sqlite','IDENTITIES_PATH':str(Path('runtime/identities.json').resolve())})
    try:
        assert select.select([process.stdout],[],[],5)[0],'Server did not start'
        url='http://127.0.0.1:'+str(json.loads(process.stdout.readline())['port'])
        def request(path,token=None,action=None):
            req=urllib.request.Request(url+path,data=json.dumps(action).encode() if action else None,headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
            try:
                with urllib.request.urlopen(req,timeout=5) as r:return r.status,r.read()
            except urllib.error.HTTPError as e:return e.code,e.read()
        assert request('/')[0]==200 and request('/staff')[0] in (401,403)
        assert request('/action',review,{'type':'add_supplier','supplier_id':sid,'name':'Synthetic supplier'})[0]==200
        assert request('/action',supplier,{'type':'register_staff','staff_id':'sample','supplier_id':sid,'name':'Synthetic person','birth_city':'Example City'})[0]==200
        rows=json.loads(request('/staff',supplier)[1]);assert len(rows)==1 and rows[0]['staff_id']=='sample' and rows[0]['status']=='submitted'
        print('Pillow and existing HTTP authentication/registration/list regressions passed.')
    finally:
        process.terminate();process.wait(timeout=5)
