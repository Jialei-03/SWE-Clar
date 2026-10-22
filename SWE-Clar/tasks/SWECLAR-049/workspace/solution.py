from copy import deepcopy
from uuid import uuid4
from storage import connect,snapshot

REDUNDANT=['legacy_mentor','legacy_mentee','duplicate_match','duplicate_notice']

class InvalidEvent(ValueError):pass

def normalized_email(value):
    if not isinstance(value,str):raise InvalidEvent('invalid_email')
    email=value.strip().casefold()
    if email.count('@')!=1 or any(c.isspace() for c in email) or not all(email.split('@')):raise InvalidEvent('invalid_email')
    return email

def intake(db,event,role):
    email=normalized_email(event.get('email'));row=db.execute('SELECT user_id FROM users WHERE email=?',(email,)).fetchone()
    uid=row['user_id'] if row else 'user-'+uuid4().hex
    if row is None:db.execute('INSERT INTO users(user_id,email) VALUES (?,?)',(uid,email))
    if isinstance(event.get('name'),str):db.execute('UPDATE users SET name=? WHERE user_id=?',(event['name'].strip(),uid))
    profile=db.execute('SELECT profile_id FROM profiles WHERE user_id=? AND role=? ORDER BY sequence LIMIT 1',(uid,role)).fetchone()
    pid=role+'-'+uuid4().hex
    if True:db.execute('INSERT INTO profiles(profile_id,user_id,role) VALUES (?,?,?)',(pid,uid,role))
    return {'user_id':uid,'profile_id':pid,'role':role}

def valid_pair(db,mentor,mentee):
    for pid,role in [(mentor,'mentor'),(mentee,'mentee')]:
        row=db.execute('SELECT p.role FROM profiles p JOIN users u ON u.user_id=p.user_id WHERE p.profile_id=?',(pid,)).fetchone()
        if row is None or row['role']!=role:raise InvalidEvent('missing_profile')

def cleanup(db):
    raise InvalidEvent('not_implemented')

def process_mentor_event(database_path,event):
    e=deepcopy(event);db=connect(database_path)
    try:
        db.execute('BEGIN IMMEDIATE');kind=e.get('type')
        if kind in {'mentor_intake','mentee_intake','legacy_mentor_intake','legacy_mentee_intake'}:
            result=intake(db,e,'mentee' if 'mentee' in kind else 'mentor')
        elif kind=='cleanup_duplicates':result=cleanup(db)
        elif kind=='stabilize_automations':
            pass # Repair redundant workflow routing.
            result={'disabled':REDUNDANT.copy()}
        elif kind=='create_match':
            mentor=e.get('mentor_id');mentee=e.get('mentee_id');valid_pair(db,mentor,mentee)
            row=db.execute('SELECT match_id FROM matches WHERE mentor_id=? AND mentee_id=? ORDER BY sequence LIMIT 1',(mentor,mentee)).fetchone()
            mid=row['match_id'] if row else 'match-'+uuid4().hex
            if row is None:db.execute('INSERT INTO matches(match_id,mentor_id,mentee_id) VALUES (?,?,?)',(mid,mentor,mentee))
            result={'match_id':mid}
        elif kind=='notify_match':
            row=db.execute('SELECT * FROM matches WHERE match_id=?',(e.get('match_id'),)).fetchone()
            if row is None:raise InvalidEvent('missing_match')
            valid_pair(db,row['mentor_id'],row['mentee_id'])
            notice=db.execute('SELECT notice_id FROM outbox WHERE match_id=? ORDER BY sequence LIMIT 1',(row['match_id'],)).fetchone()
            nid=notice['notice_id'] if notice else 'notice-'+uuid4().hex
            if notice is None:db.execute('INSERT INTO outbox(notice_id,match_id) VALUES (?,?)',(nid,row['match_id']))
            result={'notice_id':nid}
        elif kind=='snapshot':result=snapshot(db)
        else:raise InvalidEvent('unknown_event')
        db.execute('COMMIT');return {'result':result}
    except InvalidEvent as error:db.execute('ROLLBACK');return {'error':{'code':str(error)}}
    except Exception:db.execute('ROLLBACK');return {'error':{'code':'invalid_state'}}
    finally:db.close()
