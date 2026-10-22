import argparse,json,os,sys,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8188);a=p.parse_args();root=Path(tempfile.mkdtemp(prefix='shop-demo-'));config=root/'config.json';config.write_text(json.dumps({'users':{'demo':{'role':'mobile'},'manager':{'role':'manager'}},'sessions':{'demo-user':'demo','demo-manager':'manager'},'products':{'item':{'title':'Sample item','price_cents':250}}}))
os.execve('/usr/local/bin/node',['node','server/server.cjs'],{'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(root),'SHOP_CONFIG':str(config),'PORT':str(a.port),'SWECLAR_NODE_REQUIRE_ROOT':'/opt/sweclar/websocket/package.json'})
