"""Test provided real HTTP reader and JSON console, not unfinished calculations."""
import importlib.util,json,subprocess,sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread

def main():
    root=Path.cwd();expected=(root/'example.csv').read_text()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(expected.encode())
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        spec=importlib.util.spec_from_file_location('public_fetcher',root/'fetcher.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        assert mod.fetch_text(f'http://127.0.0.1:{server.server_port}/sample.csv')==expected
    finally:server.shutdown();server.server_close();thread.join()
    result=subprocess.run([sys.executable,'cli.py','--sample-source'],input=(root/'example.json').read_text(),capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert isinstance(json.loads(result.stdout),dict)
    print('Public HTTP reader and JSON console checks passed.')
if __name__=='__main__':main()
