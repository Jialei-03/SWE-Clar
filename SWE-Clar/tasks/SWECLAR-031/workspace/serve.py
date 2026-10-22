"""Loopback static hosting with byte ranges for real media seeking."""
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from functools import partial
import sys,os,re
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
 def send_head(self):
  self.byte_range=None
  raw=self.headers.get('Range')
  target=Path(self.translate_path(self.path));root=Path(self.directory).resolve()
  if not target.resolve().is_relative_to(root):self.send_error(404);return None
  if not raw:return super().send_head()
  if not target.resolve().is_relative_to(root) or not target.is_file():self.send_error(404);return None
  size=target.stat().st_size;match=re.fullmatch(r'bytes=(\d*)-(\d*)',raw)
  try:
   if not match or not any(match.groups()) or size==0:raise ValueError()
   a,b=match.groups();start=int(a) if a else max(0,size-int(b));end=min(size-1,int(b)) if a and b else size-1
   if start<0 or start> end or start>=size:raise ValueError()
  except ValueError:self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return None
  f=target.open('rb');f.seek(start);self.byte_range=(start,end);self.send_response(206);self.send_header('Content-Type',self.guess_type(str(target)));self.send_header('Content-Length',str(end-start+1));self.send_header('Content-Range',f'bytes {start}-{end}/{size}');self.send_header('Accept-Ranges','bytes');self.end_headers();return f
 def end_headers(self):
  if getattr(self,'byte_range',None) is None:self.send_header('Accept-Ranges','bytes')
  super().end_headers()
 def copyfile(self,source,output):
  if self.byte_range is None:return super().copyfile(source,output)
  remaining=self.byte_range[1]-self.byte_range[0]+1
  while remaining:
   chunk=source.read(min(65536,remaining))
   if not chunk:break
   output.write(chunk);remaining-=len(chunk)
server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','8000'))),partial(Handler,directory=sys.argv[1] if len(sys.argv)>1 else 'dist'));print(server.server_port,flush=True);server.serve_forever()
