"""Synthetic loopback-only provider for the prepared development environment."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,urllib.parse,sys
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  u=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(u.query)
  if u.path=='/maps/api/geocode/json':
   d={'status':'OK','results':[{'geometry':{'location':{'lat':.001,'lng':.002}}}]} if q.get('address')==['Synthetic address A'] else {'status':'ZERO_RESULTS','results':[]}
  elif u.path=='/v1/buildingInsights:findClosest':d={'center':{'latitude':.001,'longitude':.002},'boundingBox':{'sw':{'latitude':.0009,'longitude':.0019},'ne':{'latitude':.0011,'longitude':.0021}},'solarPotential':{'wholeRoofStats':{'areaMeters2':120.5}}}
  else:self.send_error(404);return
  raw=json.dumps(d).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
http=ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1] if len(sys.argv)>1 else '23070')),Handler);print(json.dumps({'port':http.server_port}),flush=True);http.serve_forever()
