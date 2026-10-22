import os,json,secrets
from pathlib import Path
if os.getuid()==0:os.setgroups([]);os.setgid(1000);os.setuid(1000)
root=Path('/workspace/runtime');root.mkdir(exist_ok=True)
p=root/'config.json'
if not p.exists():
 p.write_text(json.dumps({'encryption_key':secrets.token_hex(32),'sections':['Home','Sites','Plans','History','Account'],'sites':[{'id':'site-a','name':'Synthetic site','latitude':0,'longitude':0,'radius_m':100,'active':True}]}));p.chmod(0o600)
print(json.dumps({'ready':True,'config':str(p),'synthetic':True,'uid':os.getuid()}))
