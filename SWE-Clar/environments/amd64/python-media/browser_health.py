"""Decode a synthetic recording in the shared media browser as the candidate UID."""
import functools
import http.server
import json
import os
from pathlib import Path
import sys
import threading
from playwright.sync_api import sync_playwright

assert os.getuid() == 1000
assert int(next(line for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('CapEff:')).split()[1], 16) == 0
media = Path(sys.argv[1]).resolve()
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args): pass
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(media.parent)))
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        try:
            page = browser.new_page()
            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith('http://127.0.0.1:') else route.abort())
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.evaluate('''url => {const v=document.createElement('video');v.muted=true;v.src=url;document.body.replaceChildren(v);return v.play();}''', f'/{media.name}')
            page.wait_for_function("document.querySelector('video').currentTime > 1", timeout=10000)
            result = page.evaluate("() => {const v=document.querySelector('video');return {time:v.currentTime,width:v.videoWidth,frames:v.getVideoPlaybackQuality().totalVideoFrames};}")
            assert result['width'] > 0 and result['frames'] >= 5, result
            print(json.dumps({'passed':True,'engine':'firefox','version':browser.version,'uid':os.getuid(),'capabilities':0,'playback':result}))
        finally: browser.close()
finally:
    server.shutdown()
    server.server_close()
