from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from copy import deepcopy
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import re

from candidate_proxy import scrape


@contextmanager
def local_site(pages):
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path not in pages:
                self.send_error(404); return
            raw=pages[self.path].encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}',requests
    finally: server.shutdown();server.server_close();thread.join()


def test_ru_003_fetch_and_parse_actual_html():
    for variant in range(3):
        name=f'Listing {variant}'
        detail=f'''<!doctype html><html><head><link rel="canonical" href="/canonical-{variant}">
          <style>h1 {{color:red}} /* title=WRONG */</style></head><body>
          <script>var listing={{"title":"WRONG","max_persons":999}};</script>
          <h1>{name} &amp; <em>Courtyard</em></h1><address>  Example\n Square {variant} </address>
          <dl><dt>Property type</dt><dd><span>villa</span></dd>
          <dt>Max persons</dt><dd>{variant+3}</dd><dt>Contact name</dt><dd>Example Host</dd>
          <dt>Latitude</dt><dd>{12.5+variant}</dd><dt>Longitude</dt><dd>-3.25</dd>
          <dt>Pool</dt><dd>yes</dd><dt>Private note</dt><dd>do not export</dd></dl>
          <a href="tel:00000001">00 00 00 01</a><a href="tel:00000002">00-00-00-02</a></body></html>'''
        compact=f'''<html><body><h1>Compact {variant}</h1><address>Example Lane</address>
          <table><tr><th>Property type</th><td>apartment</td></tr>
          <tr><th>Max persons</th><td>2</td></tr><tr><th>Pool</th><td>no</td></tr></table></body></html>'''
        pages={'/detail':detail,'/compact':compact}
        with local_site(pages) as (base,requests):
            urls=[base+'/compact',base+'/detail'];before=deepcopy(urls)
            result=scrape(urls)
            assert urls==before and len(result)==2
            assert Counter(requests)==Counter(['/compact','/detail'])
            assert result[0]['title']==f'Compact {variant}' and result[0]['max_persons']==2
            assert result[0]==dict(title=f'Compact {variant}',property_type='apartment',address='Example Lane',max_persons=2,contact_name='',contact_phone='',url=base+'/compact',lat='',lng='',pool='no')
            row=result[1]
            assert row['title']==name+' & Courtyard'
            assert row['address']==f'Example Square {variant}'
            assert row['url']==base+f'/canonical-{variant}'
            assert row['property_type']=='villa' and row['max_persons']==variant+3
            assert row['lat']==12.5+variant and row['lng']==-3.25
            assert row['contact_name']=='Example Host' and row['pool']=='yes'
            assert row['contact_phone']=='00000001, 00000002','End-to-end scrape applies phone normalization'
            assert set(row)=={'title','property_type','address','max_persons','contact_name','contact_phone','url','lat','lng','pool'}
            assert 'private_note' not in row
            assert scrape([])==[]
            assert scrape([base+'/detail'])[0]['title']==name+' & Courtyard'
            import subprocess, json
            cli=subprocess.run([sys.executable,str(Path(os.environ['CANDIDATE_ROOT'])/'solution.py')],
                               input=json.dumps(urls),capture_output=True,text=True,timeout=10,user=1000,group=1000,extra_groups=[],cwd=os.environ['CANDIDATE_ROOT'],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
            assert cli.returncode==0, cli.stderr
            assert json.loads(cli.stdout)==result
