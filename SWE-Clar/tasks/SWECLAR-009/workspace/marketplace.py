"""Working profile/contact baseline. Complete hiring workflows after clarification."""
from common import Problem,require,fields,ident,text
from storage import public_user

def relationships(db,user):
 return [dict(r) for r in db.execute('SELECT * FROM relationships WHERE actor_id=? OR target_id=? ORDER BY kind,actor_id,target_id',(user['id'],user['id']))]

def dispatch(db,user,method,path,query,body):
 if method=='GET' and path=='/api/profiles':
  fields(query,[]);return {'profiles':[public_user(r) for r in db.execute('SELECT * FROM users ORDER BY id')]}
 if method=='PUT' and path=='/api/profile':
  fields(body,['name','bio']);name=text(body['name'],120);bio=text(body['bio'],2000,False,False);db.execute('UPDATE users SET name=?,bio=? WHERE id=?',(name,bio,user['id']));return {'user':public_user(db.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone())}
 if method=='GET' and path=='/api/relationships':
  fields(query,[]);return {'relationships':relationships(db,user)}
 if method=='POST' and path=='/api/relationships':
  fields(body,['target_id','kind','enabled']);require(ident(body['target_id']) and body['kind'] in ['follow','connect'] and type(body['enabled']) is bool)
  target=db.execute('SELECT * FROM users WHERE id=?',(body['target_id'],)).fetchone();require(target is not None,'not_found',404);require(target['id']!=user['id'])
  valid=(body['kind']=='follow' and target['role']=='employer') or (body['kind']=='connect' and user['role']==target['role']=='employee');require(valid,'denied',403)
  ids=sorted([user['id'],target['id']]) if body['kind']=='connect' else [user['id'],target['id']]
  if body['enabled']:db.execute('INSERT OR IGNORE INTO relationships VALUES(?,?,?)',(*ids,body['kind']))
  else:db.execute('DELETE FROM relationships WHERE actor_id=? AND target_id=? AND kind=?',(*ids,body['kind']))
  return {'relationships':relationships(db,user)}
 return hiring_dispatch(db,user,method,path,query,body)

def hiring_dispatch(db,user,method,path,query,body):
 # TODO: implement the clarified job, file, application, interview and analytics workflows.
 raise Problem(501,'workflow_not_implemented')
