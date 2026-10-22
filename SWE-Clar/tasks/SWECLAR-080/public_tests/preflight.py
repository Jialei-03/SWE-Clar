import os,sys,json,subprocess
sys.path.insert(0,'/opt/sweclar');from wordpress_fixture import WordPress
w=WordPress('/workspace',port=8080)
try:
 data={'url':w.url,'wordpress_root':str(w.wp),'server_pid':w.process.pid,'database_pid':w.database.process.pid,'synthetic':True}
 code="from pathlib import Path;import json,sys;p=Path('/workspace/runtime');p.mkdir(exist_ok=True);(p/'ready.json').write_text(sys.argv[1])"
 identity={'user':1000,'group':1000,'extra_groups':[]} if os.getuid()==0 else {}
 subprocess.run([sys.executable,'-c',code,json.dumps(data)],check=True,env={'PATH':os.environ['PATH'],'HOME':'/tmp'},**identity);w.detach();print(json.dumps({'ready':True,'wordpress':'6.8.3','url':w.url,'database':'real MariaDB','php_uid':1000}))
except BaseException:w.close();raise
