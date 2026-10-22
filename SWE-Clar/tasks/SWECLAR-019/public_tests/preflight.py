"""Manager-only task capability check; never loads candidate implementation."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
sys.path.insert(0, str(Path(__file__).resolve().parent))
from route_support import browser_session, run_as
from fixtures import sample_png


class Probe(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/photo.png': raw, mime = sample_png(), 'image/png'
        else:
            raw = b'''<!doctype html><button id="probe" onclick="this.textContent='clicked'">ready</button>
<svg viewBox="0 0 720 340" width="720" height="340"><polyline points="100,120 400,260" stroke="#aa4b29" fill="none"/><circle cx="100" cy="120" r="8" fill="#265747"/></svg><img src="/photo.png">'''
            mime = 'text/html'
        self.send_response(200); self.send_header('Content-Type', mime); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def log_message(self, *_): pass


def preflight():
    if os.geteuid() != 0: raise RuntimeError('Benchmark manager must finish preflight before the coding budget')
    prepared = json.loads(run_as(1000, '''import json,os,pathlib,sqlite3,sys,tempfile
from io import BytesIO
sys.path.insert(0,'/public_tests')
from fixtures import prepare_samples
from PIL import Image
assert os.getuid()==1000 and not os.access('/private',os.R_OK)
assert int(next(s for s in pathlib.Path('/proc/self/status').read_text().splitlines() if s.startswith('CapEff:')).split()[1],16)==0
p=pathlib.Path('/public_tests/accounts.json');json.loads(p.read_text());assert not os.access(p,os.W_OK)
samples=prepare_samples()
with Image.open(samples/'avatar.png') as im:im.load();assert im.size==(96,72)
with tempfile.TemporaryDirectory() as d:
 db=sqlite3.connect(pathlib.Path(d)/'probe.sqlite3');db.execute('CREATE TABLE probe(value INTEGER)');db.commit();db.execute('BEGIN IMMEDIATE');db.execute('INSERT INTO probe VALUES (1)');db.rollback();assert db.execute('SELECT COUNT(*) FROM probe').fetchone()[0]==0;db.close()
print(json.dumps({'candidate_uid':1000,'capabilities':0,'private_access_denied':True,'protected_accounts_readable':True,'png_decoder':True,'sqlite_transaction':True,'samples':str(samples)}))'''))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Probe); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with browser_session() as browser:
            page = browser.new_page(); page.goto('http://127.0.0.1:' + str(server.server_port))
            page.locator('#probe').click(); assert page.locator('#probe').inner_text() == 'clicked'
            page.wait_for_function('document.querySelector("img").naturalWidth===96')
            assert page.locator('svg').screenshot().startswith(b'\x89PNG')
            assert page.locator('polyline').evaluate('node=>node.getTotalLength()') > 300
            processes = []
            for path in Path('/proc').glob('[0-9]*/status'):
                try: lines = dict(line.split(':', 1) for line in path.read_text().splitlines() if ':' in line)
                except OSError: continue
                if any(word in lines.get('Name', '').lower() for word in ['chrome', 'chromium', 'headless']):
                    if lines.get('State', '').strip().startswith('Z'): continue
                    uid = int(lines['Uid'].split()[0]); cap = int(lines['CapEff'].strip(), 16)
                    assert uid == 1000 and cap == 0
                    processes.append({'pid': int(path.parent.name), 'uid': uid, 'capabilities': cap})
            assert processes, 'No live Chromium process identity was observed'
            prepared.update(chromium=browser.version, browser_processes=processes, actual_svg_png_http=True)
    finally: server.shutdown(); thread.join(); server.server_close()
    return {'passed': True, 'candidate_code_loaded': False, **prepared}


if __name__ == '__main__': print(json.dumps(preflight()))
