"""Independent task capability/permission check; does not load candidate code."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arena_support import browser_session


class Probe(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'''<!doctype html><button id="probe" onclick="this.textContent='clicked'">ready</button>
<canvas id="drawing" width="20" height="20"></canvas><script>
let c=document.getElementById('drawing').getContext('2d');c.fillStyle='#123456';c.fillRect(0,0,20,20);
</script>'''
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def log_message(self, *_):
        pass


def preflight():
    if os.geteuid() != 0:
        raise RuntimeError('The benchmark manager runs task preflight before the candidate budget')
    with tempfile.TemporaryDirectory(prefix='arena-clock-health-') as directory:
        root = Path(directory); root.chmod(0o755)
        clock = root / 'clock.json'; clock.write_text('{"now_ms":1000}'); clock.chmod(0o644)
        code = '''import json,os,pathlib,sys
p=pathlib.Path(sys.argv[1]);assert os.getuid()==1000;assert json.loads(p.read_text())['now_ms']==1000
for action in [lambda:p.write_text('{}'),lambda:p.unlink(),lambda:p.parent.rename(str(p.parent)+'-replaced')]:
 try:action()
 except PermissionError:pass
 else:raise AssertionError('Candidate could modify manager clock')
assert not os.access('/private',os.R_OK)
'''
        subprocess.run([sys.executable, '-I', '-c', code, str(clock)], user=1000, group=1000,
                       extra_groups=[], check=True, capture_output=True, timeout=10)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Probe)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with browser_session() as browser:
            page = browser.new_page()
            page.goto('http://127.0.0.1:' + str(server.server_port))
            page.locator('#probe').click()
            assert page.locator('#probe').inner_text() == 'clicked'
            assert page.evaluate("Array.from(document.querySelector('canvas').getContext('2d').getImageData(5,5,1,1).data)") == [18, 52, 86, 255]
            assert page.locator('#drawing').screenshot().startswith(b'\x89PNG\r\n\x1a\n')
            chromium = browser.version
    finally:
        server.shutdown(); worker.join(); server.server_close()
    return {'passed': True, 'candidate_code_loaded': False, 'chromium': chromium,
            'browser_uid': 1000, 'browser_effective_capabilities': 0,
            'actual_canvas_and_http': True, 'protected_clock_and_parent': True,
            'network': 'local loopback', 'dependencies_installed_during_attempt': False}


if __name__ == '__main__':
    print(json.dumps(preflight()))
