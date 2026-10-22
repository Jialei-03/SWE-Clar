from pathlib import Path
import os,json,socket,subprocess,time,urllib.request,urllib.parse,hashlib
def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def get_json(url):
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=2) as r:return json.load(r)
class Media:
    def __init__(self,root):self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.active={}
    def begin(self,event,key):raise NotImplementedError('Start actual authenticated RTMP ingest')
    def end(self,event):raise NotImplementedError('Finalize and inspect actual recorded media')
    def close(self):
        for event,(p,log,conf) in list(self.active.items()):
            if p.poll() is None:p.terminate();p.wait(timeout=10)
            log.close();conf.unlink(missing_ok=True)
        self.active.clear()
