import json,os,sqlite3
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from solution import process_music_action
from studio_client import StudioClient
DB=os.environ['STUDIO_DB'];CONFIG=json.loads(Path(os.environ['STUDIO_CONFIG']).read_text())
SERVICE=StudioClient(CONFIG['provider_url'],CONFIG.get('provider_token'))
with sqlite3.connect(DB) as db:
    db.execute('CREATE TABLE IF NOT EXISTS studio(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL)')
    db.execute('INSERT OR IGNORE INTO studio VALUES(1,?)',(json.dumps(CONFIG['initial_state']),))
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def reply(self,status,body):
        data=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        if self.path!='/actions':return self.reply(404,{'error':{'code':'not_found'}})
        authorization=self.headers.get('Authorization','')
        user=CONFIG['sessions'].get(authorization[7:]) if authorization.startswith('Bearer ') else None
        if user is None:return self.reply(401,{'error':{'code':'unauthenticated'}})
        try:
            action=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
            if not isinstance(action,dict):raise ValueError('invalid action')
        except Exception:return self.reply(400,{'error':{'code':'invalid_request'}})
        action['actor_id']=user;action['viewer_id']=user
        with sqlite3.connect(DB,timeout=15) as db:
            db.execute('BEGIN IMMEDIATE');state=json.loads(db.execute('SELECT state FROM studio WHERE id=1').fetchone()[0])
            if action.get('type')=='purchase_package':
                actor=state['users'].get(user,{});student=action.get('student_id')
                if not (actor.get('role')=='admin' or user==student or (actor.get('role')=='parent' and student in actor.get('student_ids',[]))):return self.reply(403,{'error':{'code':'payment_denied'}})
            try:result=process_music_action(state,action,SERVICE)
            except Exception:return self.reply(400,{'error':{'code':'invalid_request'}})
            if 'error' in result:return self.reply(400,{'error':result['error']})
            db.execute('UPDATE studio SET state=? WHERE id=1',(json.dumps(result),))
            response={'result':result.get('result',{})}
        self.reply(200,response)
class Server(ThreadingHTTPServer):request_queue_size=32
if __name__=='__main__':
    server=Server(('127.0.0.1',int(os.environ.get('PORT',0))),Handler)
    print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
