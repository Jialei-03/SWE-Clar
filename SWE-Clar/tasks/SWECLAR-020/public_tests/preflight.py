"""Protected independent preparation: reader, SQLite and real browser identity."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
sys.path.insert(0,str(Path(__file__).resolve().parent))
from attendance_support import ReaderService,browser_session,run_as


class Probe(BaseHTTPRequestHandler):
    def do_GET(self):
        raw=b'''<button id="probe" onclick="fetch('http://127.0.0.1:8081/readings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:'probe-tag',device_id:'probe-device',interaction:'tap',at:42})}).then(r=>r.json()).then(v=>this.textContent=v.reading.uid)">Read</button>'''
        self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def log_message(self,*_):pass


def main():
    if os.geteuid()!=0:raise RuntimeError('Manager-only preflight before candidate budget')
    reader=ReaderService(port=8081).start()
    try:
        run_as(1000,"""import json,os,pathlib,sqlite3,sys,tempfile
from urllib.request import Request,urlopen
assert os.getuid()==1000 and not os.access('/private',os.R_OK) and not os.access(sys.argv[1],os.R_OK)
assert not os.access('/public_tests/accounts.json',os.W_OK)
assert int(next(s for s in pathlib.Path('/proc/self/status').read_text().splitlines() if s.startswith('CapEff:')).split()[1],16)==0
with tempfile.TemporaryDirectory() as folder:
 db=sqlite3.connect(folder+'/probe.sqlite3');db.execute('CREATE TABLE probe(value INTEGER)');db.execute('INSERT INTO probe VALUES(4)');db.rollback();assert not db.execute('SELECT * FROM probe').fetchall()
r=Request('http://127.0.0.1:8081/readings',data=json.dumps({'uid':'probe-tag','device_id':'probe-device','interaction':'tap','at':42}).encode(),headers={'Content-Type':'application/json'})
with urlopen(r) as response:reading=json.load(response)['reading']
with urlopen('http://127.0.0.1:8081/readings/'+reading['id']) as response:assert json.load(response)['reading']==reading
""",reader.state)
        run_as(2000,"import os,pathlib;assert not os.access('/private',os.R_OK);assert int(next(s for s in pathlib.Path('/proc/self/status').read_text().splitlines() if s.startswith('CapEff:')).split()[1],16)==0")
        server=ThreadingHTTPServer(('127.0.0.1',0),Probe);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        processes=[]
        try:
            with browser_session() as browser:
                page=browser.new_page();page.goto('http://127.0.0.1:'+str(server.server_port));page.locator('#probe').click()
                page.wait_for_function('document.getElementById("probe").textContent==="probe-tag"')
                for proc in Path('/proc').iterdir():
                    if not proc.name.isdigit():continue
                    try:
                        status=(proc/'status').read_text();command=(proc/'cmdline').read_bytes()
                    except (FileNotFoundError,PermissionError,ProcessLookupError):continue
                    fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in status.splitlines() if ':' in line}
                    if fields.get('State','').startswith('Z') or not any(x in command for x in [b'headless_shell',b'chrome-linux']):continue
                    uid=int(fields['Uid'].split()[0]);caps=int(fields['CapEff'],16);assert uid==1000 and caps==0
                    processes.append({'pid':int(proc.name),'uid':uid,'capabilities':caps})
                assert processes;version=browser.version
        finally:server.shutdown();worker.join();server.server_close()
        reader.reset()
        Path('/private/reader-service.json').write_text(json.dumps({'pid':reader.process.pid,'state':str(reader.state),'url':reader.url}))
        print(json.dumps({'passed':True,'candidate_code_loaded':False,'candidate_uid':1000,'candidate_capabilities':0,'reader_uid':2000,'reader_storage_denied':True,'reader_private_access_denied':True,'sqlite_transaction':True,'browser_reader_http':True,'chromium':version,'browser_processes':processes,'reader_ready':reader.url,'dependencies_installed_during_attempt':False}))
    except BaseException:reader.close();raise

if __name__=='__main__':main()
