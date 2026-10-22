"""Prepared capabilities checked before candidate code is loaded."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
sys.path.insert(0, str(Path(__file__).resolve().parent))
from marketplace_support import browser_session, run_as


class Probe(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<!doctype html><button id="probe" onclick="this.textContent=\'clicked\'">ready</button>'
        self.send_response(200); self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *_): pass


def preflight():
    if os.geteuid() != 0: raise RuntimeError('Manager must complete preflight before candidate budget')
    report = json.loads(run_as(1000, '''import json,os,pathlib,sqlite3,tempfile
assert os.getuid()==1000
assert int(next(line for line in pathlib.Path('/proc/self/status').read_text().splitlines() if line.startswith('CapEff:')).split()[1],16)==0
assert not os.access('/private',os.R_OK)
for name in ['clock.json','catalog.json']:
 p=pathlib.Path('/public_tests')/name;json.loads(p.read_text());assert not os.access(p,os.W_OK)
with tempfile.TemporaryDirectory() as temporary:
 db=sqlite3.connect(pathlib.Path(temporary)/'probe.sqlite3');db.execute('CREATE TABLE probe(value INTEGER)');db.commit()
 db.execute('BEGIN IMMEDIATE');db.execute('INSERT INTO probe VALUES (1)');db.rollback()
 assert db.execute('SELECT COUNT(*) FROM probe').fetchone()[0]==0
 db.execute('INSERT INTO probe VALUES (2)');db.commit();db.close()
 db=sqlite3.connect(pathlib.Path(temporary)/'probe.sqlite3');assert db.execute('SELECT value FROM probe').fetchone()[0]==2;db.close()
print(json.dumps({'uid':os.getuid(),'capabilities':0,'sqlite':sqlite3.sqlite_version,'clock_fixture_readable_not_writable':True,'private_access_denied':True,'sqlite_commit_rollback_restart':True}))'''))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Probe)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with browser_session() as browser:
            page = browser.new_page(); page.goto('http://127.0.0.1:' + str(server.server_port))
            page.locator('#probe').click()
            assert page.locator('#probe').inner_text() == 'clicked'
            report.update(chromium=browser.version, actual_http_browser_interaction=True)
    finally:
        server.shutdown(); worker.join(); server.server_close()
    return {'passed': True, 'candidate_code_loaded': False, **report}


if __name__ == '__main__': print(json.dumps(preflight()))
