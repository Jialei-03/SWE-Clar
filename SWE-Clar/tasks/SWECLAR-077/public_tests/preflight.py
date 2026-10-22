import os,sys,json,base64
from pathlib import Path
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
sys.path.insert(0,'/public_tests');from fixtures import assets
root=Path('/workspace/runtime');root.mkdir(exist_ok=True);source=root/'source';out=root/'output';out.mkdir(exist_ok=True);assets(source,['Synthetic first line','Repeated sample line','Repeated sample line','Synthetic final line'])
page={'title':'Sample resource page','body':'Synthetic local content','sections':['Overview','Details','Next steps'],'asset_ids':['sample'],'images':[{'id':'sample','data':'data:image/png;base64,'+base64.b64encode((source/'image.png').read_bytes()).decode()}]};(out/'home.json').write_text(json.dumps(page));(root/'state.json').write_text(json.dumps({'assets':{'sample':{'path':'image.png'}},'pdfs':{'input':{'type':'pdf','path':'input.pdf'}},'letterheads':{'plain':{'path':'letterhead.docx'}}}))
print(json.dumps({'ready':True,'uid':os.getuid(),'synthetic_source':str(source),'output':str(out)}))
