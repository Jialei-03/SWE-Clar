"""Working current observations; implement the clarified rule and report behavior."""
def homes(db,user):
    if user['role']=='individual':return [r['id'] for r in db.execute('SELECT id FROM households WHERE id=?',(user['household_id'],))]
    if user['role']=='caregiver':return [r['household_id'] for r in db.execute('SELECT household_id FROM assignments WHERE user_id=? ORDER BY household_id',(user['id'],))]
    return []

def snapshot(db,home,as_of):
    result=[]
    for room in db.execute('SELECT * FROM rooms WHERE household_id=? ORDER BY id',(home['id'],)):
        row={'household_id':home['id'],'room_id':room['id'],'name':room['name'],'sensors':[]}
        for sensor in db.execute('SELECT * FROM sensors WHERE household_id=? AND room_id=? ORDER BY id',(home['id'],room['id'])):
            event=db.execute('SELECT * FROM events WHERE household_id=? AND sensor_id=? AND timestamp_ms<=? ORDER BY timestamp_ms DESC,event_id DESC LIMIT 1',(home['id'],sensor['id'],as_of)).fetchone()
            row['sensors'].append({'sensor_id':sensor['id'],'name':sensor['name'],'kind':sensor['kind'],'value':bool(event['value']) if event else None,'timestamp_ms':event['timestamp_ms'] if event else None,'stale':event is None or as_of-event['timestamp_ms']>home['freshness_minutes']*60000})
        result.append(row)
    return result

def saved_rules(db,home,room):
    return [{**dict(row),'enabled':bool(row['enabled'])} for row in db.execute('SELECT * FROM rules WHERE household_id=? AND room_id=? ORDER BY kind',(home,room))]

def save_rule(db,user,body):
    # TODO: implement the clarified edit permissions, validation and persistent replacement.
    return 501,'not_implemented'

def alerts(db,home,as_of):
    # TODO: derive actual rule alerts from stored sensor intervals.
    return []

def report(db,home,as_of):
    # TODO: derive the clarified rolling counts from stored observations and rules.
    return {'as_of':as_of,'window_start':as_of-86400000,'rooms':[]}
