from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import os,json
server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','8080'))),SimpleHTTPRequestHandler)
print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
