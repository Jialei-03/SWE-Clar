"""Starter discovery and interaction behavior; business policies need completion."""
import json,math

def blocked(db,a,b):
    return bool(db.execute('SELECT 1 FROM blocks WHERE actor=? AND target=?',(a,b)).fetchone())

def matches(db,actor,radius,role):
    source=db.execute('SELECT * FROM users WHERE id=?',(actor,)).fetchone()
    result=[]
    for u in db.execute('SELECT * FROM users ORDER BY id'):
        if u['id']==actor or (role!='all' and role!=u['role']):continue
        result.append({'id':u['id'],'display':u['display'],'role':u['role'],'shared':len(set(json.loads(source['interests'])) & set(json.loads(u['interests']))),'degree':0,'distance':math.hypot(u['x']-source['x'],u['y']-source['y'])})
    return result

def connection_allowed(db,actor,target,decision,existing):return True
def message_allowed(db,actor,target):return True
def invite_allowed(db,actor,target,group):return True
def post_allowed(db,actor,group):return True
def like_allowed(db,actor,post,group):return True
def store_like(db,actor,post):db.execute('INSERT OR IGNORE INTO likes VALUES(?,?)',(post,actor))
def membership_allowed(user,receipt):return True
def apply_membership(db,user,receipt):
    db.execute('INSERT OR IGNORE INTO payments VALUES(?,?,?)',(receipt['id'],user['id'],receipt['plan']))
    db.execute('UPDATE users SET plan=? WHERE id=?',(receipt['plan'],user['id']))
def featured_allowed(user):return True
