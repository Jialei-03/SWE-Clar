"""Independent browser/HTTP competitor monitor with persistent SQLite storage."""
import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlsplit
from common import Problem,fields,pairs,invalid_constant,require
from storage import connect,initialize,password_digest,transaction
import directory
import workflow


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self,*_):
        pass

    def send(self,status,payload,kind='application/json',filename=None):
        body=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8') if kind=='application/json' else payload
        self.send_response(status)
        self.send_header('Content-Type',kind+'; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        if filename:
            self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        db=None
        try:
            route=urlsplit(self.path)
            static={'/':('index.html','text/html'),'/ui.js':('ui.js','text/javascript'),'/style.css':('style.css','text/css')}
            if self.command=='GET' and route.path in static:
                file,kind=static[route.path]
                return self.send(200,(Path(__file__).parent/'web'/file).read_bytes(),kind)
            if self.command=='GET' and route.path=='/health':
                health_query=parse_qs(route.query,keep_blank_values=True)
                require(all(len(v)==1 for v in health_query.values()))
                fields(health_query,[])
                return self.send(200,{'ok':True})
            query=parse_qs(route.query,keep_blank_values=True);require(all(len(v)==1 for v in query.values()))
            query={k:v[0] for k,v in query.items()}
            body={}
            if self.command=='POST':
                fields(query,[])
                size=int(self.headers.get('Content-Length','0'));require(0<size<=32768)
                raw=self.rfile.read(size);require(len(raw)==size)
                body=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=invalid_constant)
                require(isinstance(body,dict))
            db=connect(self.server.db)
            if self.command=='POST' and route.path=='/api/login':
                fields(body,['id','password']);require(isinstance(body['id'],str) and isinstance(body['password'],str))
                row=db.execute('SELECT * FROM accounts WHERE id=?',(body['id'],)).fetchone()
                require(row is not None and hmac.compare_digest(row['password'],password_digest(body['password'],row['password'].split('$')[0])),'unauthorized',401)
                token=secrets.token_urlsafe(32)
                with transaction(db):
                    db.execute('INSERT INTO sessions VALUES(?,?)',(token,row['id']))
                return self.send(200,{'token':token,'account':{'id':row['id'],'name':row['name']}})
            token=self.headers.get('Authorization','');require(token.startswith('Bearer '),'unauthorized',401)
            row=db.execute('SELECT accounts.id,accounts.name FROM accounts JOIN sessions ON sessions.account_id=accounts.id WHERE token=?',(token[7:],)).fetchone()
            require(row is not None,'unauthorized',401)
            owner=row['id']
            if self.command=='POST' and route.path=='/api/logout':
                fields(body,[])
                with transaction(db):
                    db.execute('DELETE FROM sessions WHERE token=?',(token[7:],))
                return self.send(200,{'ok':True})
            if self.command=='GET' and route.path=='/api/me':
                fields(query,[])
                return self.send(200,{'account':dict(row)})
            result=directory.dispatch(db,owner,self.server.provider,self.command,route.path,query,body)
            if result is None:
                result=workflow.dispatch(db,owner,self.server.provider,self.command,route.path,query,body)
            if isinstance(result,tuple):
                payload,kind,filename=result
                self.send(200,payload,kind,filename)
            else:
                self.send(200,result)
        except Problem as error:
            self.send(error.status,{'error':{'code':error.code}})
        except (ValueError,TypeError,UnicodeError):
            self.send(400,{'error':{'code':'invalid'}})
        except sqlite3.Error:
            self.send(503,{'error':{'code':'storage_unavailable'}})
        except (BrokenPipeError,ConnectionResetError,TimeoutError):
            pass
        finally:
            if db is not None:
                db.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--fixtures',type=Path,default=Path('fixtures/demo.json'))
    parser.add_argument('--provider-url',default=os.environ.get('WATCH_SERVICE_URL','http://127.0.0.1:38920'))
    args=parser.parse_args()
    provider=args.provider_url.rstrip('/')
    allowed=urlsplit(provider)
    require(allowed.scheme=='http' and allowed.hostname=='127.0.0.1' and not allowed.username and not allowed.password and not allowed.path and not allowed.query and not allowed.fragment,'invalid_provider')
    initialize(args.db,args.fixtures,provider)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.daemon_threads=True;server.db=args.db;server.provider=provider
    print(json.dumps({'port':server.server_port}),flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
