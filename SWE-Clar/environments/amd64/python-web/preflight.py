"""Benchmark-owned capability check; does not import or execute candidate files."""
import json
import platform
import sqlite3
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright


class Probe(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'<button id="probe" onclick="this.textContent=42">probe</button>')
    def log_message(self, *_):
        pass


def preflight():
    with tempfile.TemporaryDirectory() as temp:
        if os.geteuid()==0:
            os.chmod(temp,0o777)
            subprocess.run([sys.executable,'-c',
                'import os,pathlib; assert os.getuid()==1000; assert not os.access("/private",os.R_OK); pathlib.Path("identity.txt").write_text("isolated")'],
                cwd=temp,user=1000,group=1000,extra_groups=[],check=True)
            assert (Path(temp)/'identity.txt').read_text()=='isolated'
            child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],user=1000,group=1000,extra_groups=[])
            try:
                child.terminate()
                child.wait(timeout=5)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
        path = Path(temp) / 'probe.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE probe(value TEXT)')
            db.execute('INSERT INTO probe VALUES(?)', ('isolated',))
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT value FROM probe').fetchone()[0] == 'isolated'
    server = ThreadingHTTPServer(('127.0.0.1', 0), Probe)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        with urlopen(url, timeout=5) as response:
            assert response.status == 200
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url)
                page.locator('#probe').click()
                assert page.locator('#probe').inner_text() == '42'
                browser_version = browser.version
            finally:
                browser.close()
    finally:
        server.shutdown()
        worker.join()
        server.server_close()
    return {'passed': True, 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
            'chromium': browser_version, 'architecture': platform.machine(), 'network': 'loopback-only during execution'}


if __name__ == '__main__':
    print(json.dumps(preflight()))
