"""Protected task preparation, independent of all candidate code."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conversation_support import ProviderService, browser_session, run_as
from fixtures import screenshot, photo


class Probe(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/image.png':
            body, mime = self.server.png, 'image/png'
        else:
            body, mime = b'<button id="probe" onclick="this.textContent=\'clicked\'">ready</button><img id="image" src="/image.png">', 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def main():
    if os.geteuid() != 0:
        raise RuntimeError('The manager runs task preflight before the candidate budget')
    samples = Path('/tmp/sweclar-samples')
    samples.mkdir(mode=0o755)
    raw = screenshot(['Me: The draft is ready', 'Peer: Please share the draft'])
    (samples / 'conversation.png').write_bytes(raw)
    (samples / 'light-shape.png').write_bytes(photo('white'))
    (samples / 'dark-shape.png').write_bytes(photo('#253b35'))
    for path in samples.iterdir():
        path.chmod(0o444)
    provider = ProviderService(port=8081).start()
    try:
        check = """import base64,json,os,pathlib,sys
from urllib.request import Request,urlopen
from PIL import Image
assert os.getuid()==1000
assert not os.access('/private',os.R_OK)
assert not os.access(sys.argv[1],os.R_OK)
assert int(next(s for s in pathlib.Path('/proc/self/status').read_text().splitlines() if s.startswith('CapEff:')).split()[1],16)==0
with Image.open('/tmp/sweclar-samples/conversation.png') as image: image.verify()
payload={'system_prompt':'Synthetic infrastructure probe','profile':{'tone':'neutral','goal':'clarity'},'messages':[{'sender':'me','text':'The draft is ready'}],'question':'Ready?'}
request=Request('http://127.0.0.1:8081/coach',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer synthetic-provider-token'})
with urlopen(request,timeout=5) as response:assert isinstance(json.load(response)['advice'],str)
photo=pathlib.Path('/tmp/sweclar-samples/light-shape.png').read_bytes()
payload={'preferences':{'tone':'neutral','goal':'clarity'},'images':[{'asset_id':'synthetic-probe','mime_type':'image/png','image_base64':base64.b64encode(photo).decode()}]}
request=Request('http://127.0.0.1:8081/photo-scores',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer synthetic-provider-token'})
with urlopen(request,timeout=5) as response:assert json.load(response)['scores'][0]['asset_id']=='synthetic-probe'
"""
        run_as(1000, check, provider.state)
        run_as(2000, "import os,pathlib;assert not os.access('/private',os.R_OK);assert int(next(s for s in pathlib.Path('/proc/self/status').read_text().splitlines() if s.startswith('CapEff:')).split()[1],16)==0")
        server = ThreadingHTTPServer(('127.0.0.1', 0), Probe)
        server.png = raw
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with browser_session() as browser:
                page = browser.new_page()
                page.goto('http://127.0.0.1:' + str(server.server_port))
                page.locator('#probe').click()
                assert page.locator('#probe').inner_text() == 'clicked'
                page.wait_for_function('document.getElementById("image").naturalWidth === 1100')
                assert page.locator('#image').screenshot().startswith(b'\x89PNG\r\n\x1a\n')
                version = browser.version
        finally:
            server.shutdown(); worker.join(); server.server_close()
        # Probe traffic is not part of the coding attempt. Keep the service alive.
        run_as(2000, "import pathlib,sys;pathlib.Path(sys.argv[1],'requests.jsonl').write_text('')", provider.state)
        Path('/private/provider-service.json').write_text(json.dumps({'pid': provider.process.pid, 'state': str(provider.state), 'url': provider.url}))
        print(json.dumps({'passed': True, 'candidate_code_loaded': False,
            'ocr_fixture_prevalidated': True, 'candidate_png_decode': True,
            'actual_provider_http': True, 'actual_provider_image_bytes': True, 'actual_browser_image_and_click': True,
            'chromium': version, 'browser_uid': 1000, 'provider_uid': 2000,
            'candidate_uid': 1000, 'candidate_capabilities': 0,
            'provider_state_unreadable_by_candidate': True, 'provider_cannot_read_private_tests': True,
            'provider_ready': provider.url, 'samples': str(samples), 'dependencies_installed_during_attempt': False}))
    except BaseException:
        provider.close()
        raise


if __name__ == '__main__':
    main()
