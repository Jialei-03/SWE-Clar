"""Public baseline regression; upload and trial policy are work to finish."""
import json,os,select,subprocess,sys,tempfile,uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
root=Path.cwd();cfg=root/'runtime/config.json';config=json.loads(cfg.read_text())
with tempfile.TemporaryDirectory() as tmp:
 p=subprocess.Popen([sys.executable,'server.py'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1','SAAS_CONFIG':str(cfg),'SAAS_DATABASE':tmp+'/db.sqlite','PORT':'0'})
 try:
  assert select.select([p.stdout],[],[],8)[0];base='http://127.0.0.1:'+p.stdout.readline().strip()
  def req(path,data=None,token='',origin=base):
   with urlopen(Request(origin+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','Authorization':'Bearer '+token})) as r:return r.read()
  u=json.loads(req('/register',{'email':'public@example.test','password':'public-synthetic-pass'}));t=u['token'];req('/trial',{},t);req('/rooms',{'id':'room','name':'Public room'},t);req('/content',{'id':'content','room':'room','title':'Public report','details':'Public details'},t)
  receipt='public-'+uuid.uuid4().hex;req('/issue',{'id':receipt,'user':u['id'],'plan':'basic'},origin=config['provider']);req('/activate',{'payment_id':receipt},t);assert req('/export/content',token=t).startswith(b'%PDF-');assert json.loads(req('/share',{'id':'content'},t))['title']=='Public report';print('public baseline passed')
 finally:p.terminate();p.wait(timeout=5)
