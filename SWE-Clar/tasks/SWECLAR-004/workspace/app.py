"""Offline HTTP application. All accounts and receipts are synthetic fixtures."""
import argparse
import hmac
import json
import math
import re
import secrets
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import policies
from storage import connect,initialize,password_hash,public_user


class Problem(Exception):
    def __init__(self,status,code):self.status=status;self.code=code


def require(condition,code='invalid',status=400):
    if not condition:raise Problem(status,code)


def text(value,limit):
    require(isinstance(value,str) and 1<=len(value.strip())<=limit)
    return value.strip()


def number(value,lo,hi):
    require(type(value) in (int,float) and math.isfinite(value) and lo<=value<=hi)
    return value


def fields(body,required):
    require(isinstance(body,dict) and set(body)==set(required))


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def send(self,status,data,kind='application/json'):
        raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode() if kind=='application/json' else data
        self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):self.handle_request()
    def do_POST(self):self.handle_request()
    def do_PUT(self):self.handle_request()
    def handle_request(self):
        try:
            route=urlparse(self.path)
            if self.command=='GET' and route.path in {'/','/ui.js','/style.css'}:
                file,kind={'/':('index.html','text/html'),'/ui.js':('ui.js','text/javascript'),'/style.css':('style.css','text/css')}[route.path]
                self.send(200,(Path(__file__).parent/'web'/file).read_bytes(),kind);return
            if self.command=='GET' and route.path=='/health':self.send(200,{'ok':True});return
            body={}
            if self.command in ('POST','PUT'):
                length=int(self.headers.get('Content-Length','0'));require(0<length<=16384)
                body=json.loads(self.rfile.read(length),parse_constant=lambda _:None)
                require(isinstance(body,dict))
            with connect(self.server.db_path) as db:
                result=self.dispatch(db,route,body)
            self.send(200,result)
        except Problem as e:self.send(e.status,{'error':{'code':e.code}})
        except (ValueError,UnicodeError):self.send(400,{'error':{'code':'invalid'}})
    def user(self,db):
        auth=self.headers.get('Authorization','')
        require(auth.startswith('Bearer '),'unauthorized',401)
        row=db.execute('SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=?',(auth[7:],)).fetchone()
        require(row is not None,'unauthorized',401)
        return row
    def target(self,db,body):
        require(isinstance(body.get('target'),str))
        row=db.execute('SELECT * FROM users WHERE id=?',(body['target'],)).fetchone()
        require(row is not None,'not_found',404)
        return row['id']
    def group(self,db,ident):
        require(isinstance(ident,str))
        row=db.execute('SELECT * FROM groups WHERE id=?',(ident,)).fetchone()
        require(row is not None,'not_found',404)
        return row
    def dispatch(self,db,route,body):
        path=route.path;method=self.command
        if method=='POST' and path=='/api/login':
            fields(body,{'id','password'});require(isinstance(body['id'],str) and isinstance(body['password'],str))
            row=db.execute('SELECT * FROM users WHERE id=?',(body['id'],)).fetchone()
            require(row is not None and hmac.compare_digest(row['password_hash'],password_hash(body['password'])),'unauthorized',401)
            token=secrets.token_urlsafe(32);db.execute('INSERT INTO sessions VALUES(?,?)',(token,row['id']))
            return {'token':token,'user':public_user(row)}
        user=self.user(db);actor=user['id']
        if method=='POST' and path=='/api/logout':
            fields(body,set());db.execute('DELETE FROM sessions WHERE token=?',(self.headers['Authorization'][7:],));return {'ok':True}
        if method=='GET' and path=='/api/me':return {'user':public_user(user)}
        if method=='GET' and path=='/api/people':
            return {'people':[dict(r) for r in db.execute('SELECT id,display,role FROM users ORDER BY id')]}
        if method=='PUT' and path=='/api/profile':
            fields(body,{'interests','x','y'});items=body['interests']
            require(isinstance(items,list) and len(items)<=10 and all(isinstance(i,str) and re.fullmatch('[a-z][a-z0-9_-]{0,23}',i) for i in items) and len(set(items))==len(items))
            x=number(body['x'],-1000,1000);y=number(body['y'],-1000,1000)
            db.execute('UPDATE users SET interests=?,x=?,y=? WHERE id=?',(json.dumps(items),x,y,actor))
            return {'user':public_user(db.execute('SELECT * FROM users WHERE id=?',(actor,)).fetchone())}
        if method=='GET' and path=='/api/matches':
            query=parse_qs(route.query,keep_blank_values=True);require(set(query)<={'radius','role'} and all(len(v)==1 for v in query.values()))
            radius=number(float(query.get('radius',['100'])[0]),0,3000);role=query.get('role',['all'])[0]
            require(role in {'all','user','business'})
            return {'matches':policies.matches(db,actor,radius,role)}
        if method=='POST' and path=='/api/connection':
            fields(body,{'target','decision'});target=self.target(db,body);decision=body['decision']
            require(target!=actor and decision in {'request','accept'})
            a,b=sorted([actor,target]);existing=db.execute('SELECT * FROM connections WHERE a=? AND b=?',(a,b)).fetchone()
            require(policies.connection_allowed(db,actor,target,decision,existing),'denied',403)
            if existing is None:db.execute('INSERT INTO connections VALUES(?,?,?,0)',(a,b,actor))
            elif decision=='accept':db.execute('UPDATE connections SET accepted=1 WHERE a=? AND b=?',(a,b))
            row=db.execute('SELECT * FROM connections WHERE a=? AND b=?',(a,b)).fetchone()
            return {'accepted':bool(row['accepted'])}
        if method=='POST' and path=='/api/block':
            fields(body,{'target','blocked'});target=self.target(db,body)
            require(target!=actor and type(body['blocked']) is bool)
            if body['blocked']:db.execute('INSERT OR IGNORE INTO blocks VALUES(?,?)',(actor,target))
            else:db.execute('DELETE FROM blocks WHERE actor=? AND target=?',(actor,target))
            return {'ok':True}
        if method=='POST' and path=='/api/message':
            fields(body,{'target','content'});target=self.target(db,body);content=text(body['content'],2000)
            require(target!=actor and policies.message_allowed(db,actor,target),'denied',403)
            ident=uuid.uuid4().hex;db.execute('INSERT INTO messages VALUES(?,?,?,?)',(ident,actor,target,content));return {'id':ident}
        if method=='POST' and path=='/api/group':
            fields(body,{'name'});name=text(body['name'],80);ident=uuid.uuid4().hex
            db.execute('INSERT INTO groups VALUES(?,?,?)',(ident,actor,name));db.execute('INSERT INTO members VALUES(?,?)',(ident,actor));return {'id':ident}
        if method=='POST' and path=='/api/invite':
            fields(body,{'group_id','target'});group=self.group(db,body['group_id']);target=self.target(db,body)
            require(policies.invite_allowed(db,actor,target,group),'denied',403)
            db.execute('INSERT OR IGNORE INTO members VALUES(?,?)',(group['id'],target));return {'ok':True}
        if method=='POST' and path=='/api/post':
            fields(body,{'group_id','content','featured'});group=self.group(db,body['group_id']);content=text(body['content'],2000)
            require(type(body['featured']) is bool)
            require(policies.post_allowed(db,actor,group),'denied',403)
            require(not body['featured'] or policies.featured_allowed(user),'denied',403)
            ident=uuid.uuid4().hex;db.execute('INSERT INTO posts VALUES(?,?,?,?,?)',(ident,group['id'],actor,content,int(body['featured'])));return {'id':ident}
        if method=='POST' and path=='/api/like':
            fields(body,{'post_id'});require(isinstance(body['post_id'],str))
            post=db.execute('SELECT * FROM posts WHERE id=?',(body['post_id'],)).fetchone();require(post is not None,'not_found',404)
            group=self.group(db,post['group_id']);require(policies.like_allowed(db,actor,post,group),'denied',403)
            policies.store_like(db,actor,post['id'])
            return {'likes':db.execute('SELECT COUNT(*) FROM likes WHERE post_id=?',(post['id'],)).fetchone()[0]}
        if method=='POST' and path=='/api/subscribe':
            fields(body,{'receipt_id'});require(isinstance(body['receipt_id'],str))
            receipt=next((r for r in self.server.fixtures['receipts'] if r['id']==body['receipt_id']),None)
            require(receipt is not None and policies.membership_allowed(user,receipt),'denied',403)
            # Serialize receipt consumption and the active-plan update together.
            db.execute('BEGIN IMMEDIATE')
            policies.apply_membership(db,user,receipt)
            return {'plan':db.execute('SELECT plan FROM users WHERE id=?',(actor,)).fetchone()[0]}
        if method=='GET' and path=='/api/dashboard':
            connections=[]
            for c in db.execute('SELECT * FROM connections WHERE a=? OR b=?',(actor,actor)):
                target=c['b'] if c['a']==actor else c['a']
                if not policies.blocked(db,actor,target):connections.append({'target':target,'accepted':bool(c['accepted']),'incoming':c['requester']!=actor})
            groups=[dict(g) for g in db.execute('SELECT groups.* FROM groups JOIN members ON groups.id=members.group_id WHERE user_id=? ORDER BY groups.rowid',(actor,)) if not policies.blocked(db,actor,g['owner'])]
            group_ids={g['id'] for g in groups};posts=[]
            for p in db.execute('SELECT * FROM posts ORDER BY rowid'):
                if p['group_id'] in group_ids and not policies.blocked(db,actor,p['author']):
                    item=dict(p);item['featured']=bool(item['featured']);item['likes']=db.execute('SELECT COUNT(*) FROM likes WHERE post_id=?',(p['id'],)).fetchone()[0];posts.append(item)
            messages=[dict(m) for m in db.execute('SELECT * FROM messages WHERE sender=? OR recipient=? ORDER BY rowid',(actor,actor)) if not policies.blocked(db,m['sender'],m['recipient'])]
            return {'connections':connections,'groups':groups,'posts':posts,'messages':messages,
                'blocked':[r['target'] for r in db.execute('SELECT target FROM blocks WHERE actor=? ORDER BY target',(actor,))]}
        raise Problem(404,'not_found')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',default='network.sqlite');parser.add_argument('--fixtures',default='fixtures/demo.json');parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args();fixtures=json.loads(Path(args.fixtures).read_text());initialize(args.db,fixtures)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.db_path=args.db;server.fixtures=fixtures
    print(server.server_port,flush=True)
    try:server.serve_forever()
    finally:server.server_close()


if __name__=='__main__':main()
