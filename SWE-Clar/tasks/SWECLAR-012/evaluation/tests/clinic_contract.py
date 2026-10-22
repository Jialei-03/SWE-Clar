"""Private RU-aligned checks of real HTTP, rendered Flutter and durable state."""
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import sys
import traceback

sys.path.insert(0, '/public_tests')
from clinic_support import CandidateFailure, ClinicSession, EnvironmentFailure

NOW = 2070000000000
MINUTE = 60000
HOUR = 3600000
FIELDS = ('id','patient_id','clinic_id','provider_id','slot_id','start_ms','end_ms',
          'status','revision','cancel_reason','created_at_ms','updated_at_ms')


class PrerequisiteFailure(CandidateFailure):
    def __init__(self, ru, detail):
        self.ru = ru
        super().__init__(detail)


class Checks:
    def __init__(self):
        self.passed = []

    def require(self, condition, detail):
        if not condition:
            raise CandidateFailure(detail)
        self.passed.append(detail)

    def response(self, result, status, detail, code=None, prerequisite=None):
        valid = result['status'] == status and (code is None or result['body'].get('error') == code)
        if not valid and prerequisite:
            raise PrerequisiteFailure(prerequisite, detail + ': ' + json.dumps(result))
        self.require(valid, detail + ': expected ' + str(status))
        return result['body']


def fixture(tag):
    ids = {key:tag+'_'+key for key in ('clinic_a','clinic_b','empty','provider_a','provider_b','provider_c',
          'patient_a','patient_b','patient_c','staff_a','staff_a2','staff_b','past','edge','slot_a','slot_b','slot_c','slot_d','other','foreign')}
    data = {
        'clinics':[{'id':ids['clinic_a'],'label':'Synthetic Clinic Meadow'},
                   {'id':ids['clinic_b'],'label':'Synthetic Clinic Harbor'},
                   {'id':ids['empty'],'label':'Synthetic Empty Clinic'}],
        'providers':[{'id':ids['provider_a'],'clinic_id':ids['clinic_a'],'label':'Synthetic Provider Alpha'},
                     {'id':ids['provider_b'],'clinic_id':ids['clinic_a'],'label':'Synthetic Provider Beta'},
                     {'id':ids['provider_c'],'clinic_id':ids['clinic_b'],'label':'Synthetic Provider Gamma'}],
        'users':[], 'slots':[]}
    for key in ('patient_a','patient_b','patient_c','staff_a','staff_a2','staff_b'):
        data['users'].append({'id':ids[key],'username':tag+'.'+key,'password':'Synthetic-only-'+tag+'-'+key,
                              'label':'Synthetic '+key.replace('_',' ').title(),
                              'role':'staff' if key.startswith('staff') else 'patient',
                              'clinic_id':ids['clinic_b'] if key=='staff_b' else (ids['clinic_a'] if key.startswith('staff') else None)})
    for key, provider, offset in [('past','provider_a',-30*MINUTE),('edge','provider_a',0),
                                 ('slot_a','provider_a',HOUR),('slot_b','provider_a',2*HOUR),
                                 ('slot_c','provider_a',3*HOUR),('slot_d','provider_a',4*HOUR),
                                 ('other','provider_b',HOUR),('foreign','provider_c',HOUR)]:
        data['slots'].append({'id':ids[key],'provider_id':ids[provider],'start_ms':NOW+offset})
    return data, ids


class Case:
    def __init__(self, tag, checks):
        self.data, self.ids = fixture(tag)
        self.s = ClinicSession(fixture=self.data, now_ms=NOW)
        self.c = checks
        self.tokens = {}

    def __enter__(self):
        self.s.__enter__()
        try:
            for key in ('patient_a','patient_b','patient_c','staff_a','staff_a2','staff_b'):
                user = self.user(key)
                body = self.c.response(self.s.api('POST','/api/login',{'username':user['username'],'password':user['password']}),
                                       200,'Fixture authentication for '+key,prerequisite='RU-001')
                self.tokens[key] = body['token']
            return self
        except Exception:
            self.s.close()
            raise

    def __exit__(self, *args):
        self.s.__exit__(*args)

    def user(self, key):
        return next(u for u in self.data['users'] if u['id']==self.ids[key])

    def api(self, method, path, body=None, actor='patient_a'):
        return self.s.api(method,path,body,self.tokens[actor] if actor else None)

    def book(self, request, slot='slot_a', actor='patient_a', **extra):
        return self.api('POST','/api/book',{'request_id':request,'slot_id':self.ids.get(slot,slot),**extra},actor)

    def created(self, request, slot='slot_a', actor='patient_a'):
        return self.c.response(self.book(request,slot,actor),201,'Create prerequisite appointment',prerequisite='RU-003')['appointment']

    def detail(self, appointment, actor='patient_a'):
        value=self.api('GET','/api/appointments/'+appointment,actor=actor)
        return self.c.response(value,200,'Read authorized appointment',prerequisite='RU-003')['appointment']

    def history(self, actor='patient_a', suffix=''):
        return self.c.response(self.api('GET','/api/appointments'+suffix,actor=actor),200,'Read scoped history',prerequisite='RU-003')['appointments']

    def free(self, provider='provider_a', clinic='clinic_a'):
        path='/api/slots?clinic_id='+self.ids[clinic]
        if provider:path+='&provider_id='+self.ids[provider]
        body=self.c.response(self.api('GET',path),200,'Read availability',prerequisite='RU-002')
        return body['slots']

    def free_ids(self):
        return [r['id'] for r in self.free()]

    def cancel(self, appointment, reason='Synthetic schedule change', actor='patient_a'):
        return self.api('POST','/api/appointments/'+appointment+'/cancel',{'reason':reason},actor)

    def move(self, appointment, operation, target, revision, actor='patient_a'):
        return self.api('POST','/api/appointments/'+appointment+'/move',
                        {'operation_id':operation,'to_slot_id':self.ids.get(target,target),'expected_revision':revision},actor)

    def ui(self, kind, **args):
        return self.s.ui({'op':kind,**args})

    def ui_login(self, actor):
        user=self.user(actor)
        self.ui('mount')
        self.ui('enter_text',key='login-username',text=user['username'])
        self.ui('enter_text',key='login-password',text=user['password'])
        row=self.ui('tap',key='login-submit')
        self.c.require(row['error'] is None and user['label'] in row['texts'],'Real UI authenticated identity')
        return row


def core(appointment):
    return {key:appointment[key] for key in FIELDS}


def private_not_found(value):
    return value['status']==404 and value['body'].get('error')=='not_found' and not any(k in value['body'] for k in FIELDS if k!='id')


def rendered_time(row, key, value):
    """Find the expected UTC instant in the actual keyed card's readable text.

    Accept common numeric and named-month orders, padding, separators, split
    Text widgets, 12/24-hour clocks and UTC/GMT/Z/+00:00 notation. A slot time
    is minute-aligned, so omission of zero seconds preserves all information.
    """
    text = ' '.join(str(t) for t in row.get('keyed_texts', {}).get(key, []))
    instant = datetime.fromtimestamp(value / 1000, timezone.utc)
    if not re.search(r'\b(?:UTC|GMT)\b|\dZ\b|\+00:?00\b', text, re.I):
        return False
    year = str(instant.year)
    month = '0?' + str(instant.month) if instant.month < 10 else str(instant.month)
    day = '0?' + str(instant.day) if instant.day < 10 else str(instant.day)
    sep = r'\s*[-/.]\s*'
    name = '(?:' + instant.strftime('%b') + '|' + instant.strftime('%B') + ')'
    dates = [year + sep + month + sep + day,
             day + sep + month + sep + year,
             month + sep + day + sep + year,
             day + r'\s+' + name + r'\s*,?\s*' + year,
             name + r'\s+' + day + r'\s*,?\s*' + year]
    minute = f'{instant.minute:02d}'
    hour = ('0?' + str(instant.hour)) if instant.hour < 10 else str(instant.hour)
    clock24 = hour + ':' + minute + r'(?::00(?:\.0+)?)?(?![\d:.]|\s*[AP]M\b)'
    h12 = instant.hour % 12 or 12
    hour12 = ('0?' + str(h12)) if h12 < 10 else str(h12)
    clock12 = hour12 + ':' + minute + r'(?::00(?:\.0+)?)?\s*' + ('AM' if instant.hour < 12 else 'PM') + r'\b'
    for date in dates:
        for match in re.finditer(r'(?<!\d)' + date + r'(?!\d)', text, re.I):
            # Date and clock can appear in either order in the keyed card.
            clock_text=text[:match.start()]+' '+text[match.end():]
            if re.search(r'(?<![\d:])(?:' + clock12 + '|' + clock24 + r')', clock_text, re.I):
                return True
    return False


def rendered_status(row, key, status):
    text = ' '.join(str(t) for t in row.get('keyed_texts', {}).get(key, []))
    patterns = {'active': r'\b(?:active|booked|confirmed)\b',
                'cancelled': r'\b(?:cancelled|canceled)\b'}
    opposite = 'cancelled' if status == 'active' else 'active'
    return bool(re.search(patterns[status], text, re.I)) and not re.search(patterns[opposite], text, re.I)


def gate_one(c):
    with Case('auth',c) as x:
        for path in ['/api/me','/api/catalog','/api/slots?clinic_id='+x.ids['clinic_a']]:
            c.response(x.api('GET',path,actor=None),401,'Unauthenticated protected route','unauthenticated')
            c.response(x.s.api('GET',path,token='forged-session'),401,'Forged bearer token','unauthenticated')
        for username,password in [('unknown-account','invented'),(x.user('patient_a')['username'],'incorrect')]:
            c.response(x.s.api('POST','/api/login',{'username':username,'password':password}),401,'Invalid credentials','invalid_credentials')
        c.response(x.s.api('POST','/api/login',{'username':True,'password':4}),400,'Invalid credential types','invalid_request')
        user=x.user('patient_a')
        login=c.response(x.s.api('POST','/api/login',{'username':user['username'],'password':user['password'],'role':'staff','clinic_id':x.ids['clinic_b']}),200,'Additional session')
        c.require(all(login['user'][k]==user[k] for k in ('id','label','role','clinic_id')),'Login ignores supplied role/clinic')
        tokens=[*x.tokens.values(),login['token']]
        c.require(all(isinstance(t,str) and len(t)>=32 for t in tokens) and len(set(tokens))==len(tokens),'Session tokens nontrivial and independent')
        database=x.s.read(x.s.database)
        c.require(database.startswith(b'SQLite format 3\x00'),'Real SQLite storage')
        c.require(all(u['password'].encode() not in database for u in x.data['users']),'No cleartext fixture passwords in SQLite')
        c.require(all(t.encode() not in database for t in tokens),'No cleartext session tokens in SQLite')
        catalog=c.response(x.api('GET','/api/catalog'),200,'Catalog reads through HTTP')
        c.require({r['id'] for r in catalog['clinics']}=={r['id'] for r in x.data['clinics']},'All synthetic clinics remain data-driven')
        c.require({tuple(p[k] for k in ('id','clinic_id','label')) for p in catalog['providers']}=={tuple(p[k] for k in ('id','clinic_id','label')) for p in x.data['providers']},'Provider catalog preserves fixture data')
        c.require(not any(value in json.dumps(catalog) for value in [*(u['password'] for u in x.data['users']),*(u['id'] for u in x.data['users'] if u['id']!=x.ids['patient_a']),*tokens]),'Catalog does not expose account/credential material')
        x.s.set_clock(NOW+MINUTE)
        c.require(x.api('GET','/api/catalog')['body']['now_ms']==NOW+MINUTE,'Catalog reads changed benchmark clock')
        x.s.restart_backend()
        c.response(x.s.api('GET','/api/me',token=login['token']),200,'Session survives actual restart')
        c.response(x.s.api('POST','/api/logout',{},login['token']),200,'Logout one session')
        x.s.restart_backend()
        c.response(x.s.api('GET','/api/me',token=login['token']),401,'Logout survives actual restart')
        c.response(x.api('GET','/api/me'),200,'Other session survives logout')
        row=x.ui_login('patient_a')
        c.require('nav-publish' not in row['keyed_texts'],'Patient UI has no staff publication action')
        row=x.ui('select',key='clinic-select',value=x.ids['clinic_b'])
        c.require(x.data['clinics'][1]['label'] in row['texts'],'Actual clinic dropdown selection')
        x.ui('select',key='provider-select',value=x.ids['provider_c'])
        row=x.ui('tap',key='logout')
        c.require('login-username' in row['keyed_texts'] and not any(k.startswith('slot-') for k in row['keyed_texts']),'Logout clears actual user-specific widgets')
        x.ui('enter_text',key='login-username',text=user['username'])
        x.ui('enter_text',key='login-password',text='incorrect')
        row=x.ui('tap',key='login-submit')
        c.require(row['error'] is not None and row['error'] in row['texts'],'Real failed login visibly reports error')
        x.ui('capture',name='authentication.png')


def gate_two(c):
    with Case('slots',c) as x:
        base={'id':'visible-added','provider_id':x.ids['provider_a'],'start_ms':NOW+6*HOUR}
        c.response(x.api('POST','/api/slots',base,actor='patient_a'),403,'Patient cannot publish','forbidden')
        c.response(x.api('POST','/api/slots',base,actor='staff_b'),403,'Foreign-clinic staff cannot publish','forbidden')
        c.response(x.api('POST','/api/slots',{**base,'provider_id':'unknown'},actor='staff_a'),404,'Unknown publication provider','not_found')
        before=x.free()
        for value in [NOW,NOW-MINUTE,NOW+1,True,1.5,'2070000000000',-MINUTE,4102444800000]:
            c.response(x.api('POST','/api/slots',{**base,'start_ms':value},actor='staff_a'),400,'Invalid publication time '+repr(value),'invalid_request')
        for identifier in ['', '_bad', 'x'*65, 'space id', None]:
            c.response(x.api('POST','/api/slots',{**base,'id':identifier},actor='staff_a'),400,'Invalid slot identifier','invalid_request')
        c.require(x.free()==before,'Rejected publication preserves slots')
        made=c.response(x.api('POST','/api/slots',base,actor='staff_a'),201,'Create valid staff slot')['slot']
        c.require(made['start_ms']==base['start_ms'] and made['end_ms']==base['start_ms']+30*MINUTE and made['clinic_id']==x.ids['clinic_a'],'Slot has actual provider, clinic and duration')
        c.response(x.api('POST','/api/slots',base,actor='staff_a'),409,'Duplicate slot id','conflict')
        c.response(x.api('POST','/api/slots',{**base,'id':'overlap','start_ms':base['start_ms']+MINUTE},actor='staff_a'),409,'Overlapping provider interval','conflict')
        c.response(x.api('POST','/api/slots',{**base,'id':'adjacent','start_ms':base['start_ms']+30*MINUTE},actor='staff_a'),201,'Adjacent interval accepted')
        c.response(x.api('POST','/api/slots',{**base,'id':'equal-time-other','provider_id':x.ids['provider_b']},actor='staff_a'),201,'Different provider may share time')
        slots=x.free(provider=None)
        c.require(slots==sorted(slots,key=lambda s:(s['start_ms'],s['id'])),'Availability uses time then identifier ordering')
        c.require(x.ids['past'] not in [s['id'] for s in slots] and x.ids['edge'] not in [s['id'] for s in slots],'Availability strictly excludes past and exact-now slots')
        c.require(all(r['provider_id']==x.ids['provider_a'] for r in x.free()),'Provider filter respected')
        c.require(x.free(provider=None,clinic='empty')==[],'Existing empty clinic yields empty list')
        for suffix,status in [('clinic_id=unknown',404),('clinic_id='+x.ids['clinic_a']+'&provider_id=unknown',404),('clinic_id='+x.ids['clinic_a']+'&provider_id='+x.ids['provider_c'],400)]:
            c.response(x.api('GET','/api/slots?'+suffix),status,'Invalid filter rejected')
        duplicate={**base,'id':'racing','start_ms':NOW+8*HOUR}
        req={'method':'POST','path':'/api/slots','body':duplicate,'token':x.tokens['staff_a']}
        races=x.s.parallel_api([dict(req) for _ in range(6)])
        c.require(sorted(r['status'] for r in races)==[201]+[409]*5,'Concurrent duplicate publication creates one slot')
        x.s.restart_backend()
        c.require('racing' in x.free_ids(),'Published slot survives restart')
        x.ui_login('staff_a')
        x.ui('tap',key='nav-publish')
        x.ui('enter_text',key='slot-id',text='rendered-slot')
        x.ui('enter_text',key='slot-start',text=str(NOW+10*HOUR))
        x.ui('tap',key='publish-submit')
        row=x.ui('tap',key='slot-rendered-slot')
        c.require(rendered_time(row,'slot-rendered-slot',NOW+10*HOUR),'Flutter publishes and renders a real time')
        c.require('rendered-slot' in x.free_ids(),'Flutter publication reaches actual service')
        x.ui('tap',key='nav-publish')
        x.ui('enter_text',key='slot-id',text='bad-ui-slot')
        x.ui('enter_text',key='slot-start',text=str(NOW))
        row=x.ui('tap',key='publish-submit')
        c.require(row['error'] is not None and row['error'] in row['texts'] and 'bad-ui-slot' not in x.free_ids(),'Rejected UI publication is visible and not persisted')


def gate_three(c):
    with Case('booking',c) as x:
        c.response(x.book('staff-forged',actor='staff_a',patient_id=x.ids['patient_a']),403,'Staff cannot create patient booking','forbidden')
        c.response(x.book('unknown','unknown'),404,'Unknown booking slot','not_found')
        for slot in ('past','edge'):
            c.response(x.book('bad-'+slot,slot),409,'Booking requires strictly future slot','conflict')
        c.response(x.book('bad key'),400,'Invalid request identifier','invalid_request')
        a=c.response(x.book('intent',patient_id=x.ids['patient_b'],role='staff'),201,'Create patient booking')['appointment']
        original=core(a)
        expected={'patient_id':x.ids['patient_a'],'clinic_id':x.ids['clinic_a'],'provider_id':x.ids['provider_a'],
                  'slot_id':x.ids['slot_a'],'start_ms':NOW+HOUR,'end_ms':NOW+HOUR+30*MINUTE,
                  'status':'active','revision':1,'cancel_reason':None,'created_at_ms':NOW,'updated_at_ms':NOW}
        c.require(all(a[k]==v for k,v in expected.items()) and isinstance(a['id'],str) and bool(a['id']),'Booking uses authenticated identity and complete initial fields')
        c.require(x.ids['slot_a'] not in x.free_ids(),'Booking actually occupies slot')
        c.require(core(c.response(x.book('intent'),200,'Identical booking replay')['appointment'])==original,'Replay returns the original appointment')
        c.response(x.book('intent','slot_b'),409,'Request key cannot change original slot','conflict')
        c.response(x.book('different-request'),409,'Another request cannot occupy booked slot','conflict')
        second=x.created('intent','other',actor='patient_b')
        third=x.created('another','slot_b')
        c.require(len({a['id'],second['id'],third['id']})==3,'Opaque appointment IDs distinct across users')
        c.require([r['id'] for r in x.history()]==[a['id'],third['id']],'Patient history own records sorted by current time')
        c.require({r['id'] for r in x.history('staff_a')}=={a['id'],second['id'],third['id']},'Clinic staff sees clinic appointments')
        c.require(x.history('staff_b')==[],'Foreign clinic staff history empty')
        c.require(x.history(suffix='?patient_id='+x.ids['patient_b']+'&role=staff')==x.history(),'Query parameters cannot widen identity scope')
        for actor in ('patient_b','staff_b'):
            actual=x.api('GET','/api/appointments/'+a['id'],actor=actor)
            absent=x.api('GET','/api/appointments/nonexistent',actor=actor)
            c.require(private_not_found(actual) and private_not_found(absent),'Foreign and absent appointment indistinguishable')
        x.s.restart_backend()
        c.require(core(x.detail(a['id']))==original,'Actual restart retains booking')
        x.s.set_clock(NOW+HOUR)
        c.require(core(c.response(x.book('intent'),200,'Booking replay at start')['appointment'])==original,'Replay bypasses new-booking future cutoff')
        c.require(any(row['id']==a['id'] for row in x.history()),'Past appointments remain in scoped history')
    with Case('book-no-extra-policy',c) as x:
        created=[x.created('coincident-'+str(i),slot) for i,slot in enumerate(('slot_a','other','foreign'))]
        c.require([row['id'] for row in x.history()]==[row['id'] for row in sorted(created,key=lambda a:(a['start_ms'],a['id']))],'Same-time patient bookings across providers and clinics are permitted and tie-sorted')
    with Case('book-races',c) as x:
        req={'method':'POST','path':'/api/book','body':{'request_id':'same-request','slot_id':x.ids['slot_a']},'token':x.tokens['patient_a']}
        values=x.s.parallel_api([dict(req) for _ in range(8)])
        c.require(sorted(r['status'] for r in values)==[200]*7+[201],'Concurrent identical requests have one creation and seven replays')
        c.require(len({r['body']['appointment']['id'] for r in values})==1,'Concurrent replay IDs are identical')
        requests=[{'method':'POST','path':'/api/book','body':{'request_id':'race-'+str(i),'slot_id':x.ids['slot_b']},'token':x.tokens['patient_a' if i%2 else 'patient_b']} for i in range(8)]
        values=x.s.parallel_api(requests)
        c.require(sorted(r['status'] for r in values)==[201]+[409]*7,'Concurrent competing patients have exactly one winner')
        before=x.history('staff_a')
        x.s.storage_readonly(True)
        failed=x.book('recoverable','slot_c')
        x.s.storage_readonly(False)
        c.response(failed,500,'Read-only storage rejects booking','storage_error')
        c.require(x.history('staff_a')==before and x.ids['slot_c'] in x.free_ids(),'Failed booking retains history and occupancy')
        c.response(x.book('recoverable','slot_c'),201,'Failed request id remains reusable')
    with Case('book-lifecycle',c) as x:
        a=x.created('original')
        moved=c.response(x.move(a['id'],'move-for-replay','slot_b',1),200,'Move prerequisite for replay',prerequisite='RU-005')['appointment']
        c.require(core(c.response(x.book('original'),200,'Book replay after move')['appointment'])==core(moved),'Booking replay returns current moved fields')
        cancelled=c.response(x.cancel(a['id']),200,'Cancel prerequisite for replay',prerequisite='RU-004')['appointment']
        c.require(core(c.response(x.book('original'),200,'Book replay after cancel')['appointment'])==core(cancelled),'Booking replay returns current cancelled fields')
    with Case('book-ui',c) as x:
        x.ui_login('patient_a')
        x.s.proxy.lose_next('/api/book')
        row=x.ui('tap',key='book-'+x.ids['slot_a'])
        c.require(row['error'] is not None and row['error'] in row['texts'],'Lost booking response shown as visible error')
        saved=x.history()
        c.require(len(saved)==1,'First UI booking really committed before lost response')
        row=x.ui('tap',key='book-'+x.ids['slot_a'])
        c.require(rendered_status(row,'appointment-'+saved[0]['id'],'active'),'Retry shows real active appointment card')
        requests=[r for r in x.s.proxy.requests if r['path']=='/api/book']
        c.require(len(requests)==2 and requests[0]['body']==requests[1]['body'] and [r['status'] for r in requests]==[201,200],'UI booking retry retains action identifier')
        x.ui('tap',key='nav-availability')
        x.s.proxy.lose_next('/api/book',hold=True)
        x.ui('tap',key='book-'+x.ids['slot_b'],wait=False)
        x.ui('tap',key='book-'+x.ids['slot_b'],wait=False)
        x.s.proxy.release_response()
        x.ui('inspect')
        later=[r for r in x.s.proxy.requests if r['path']=='/api/book' and r['body'].get('slot_id')==x.ids['slot_b']]
        c.require(later and len({r['body']['request_id'] for r in later})==1 and len(x.history())==2,'Pending double tap creates one booking intent and one new appointment')
        x.ui('capture',name='booked.png')


def gate_four(c):
    with Case('cancel',c) as x:
        a=x.created('cancel-origin')
        for actor in ('patient_b','staff_b'):
            c.require(private_not_found(x.cancel(a['id'],actor=actor)) and private_not_found(x.cancel('missing',actor=actor)),'Cancellation conceals foreign and unknown appointments')
        for reason in ['', '\u2003\t\n', 'x'*201, None, 7, True]:
            c.response(x.cancel(a['id'],reason),400,'Invalid cancellation reason','invalid_request')
        c.require(core(x.detail(a['id']))==core(a),'Invalid cancellation leaves original record')
        x.s.set_clock(NOW+MINUTE)
        reason='\u2003'+'界'*200+'\u2003'
        cancelled=c.response(x.cancel(a['id'],reason,actor='staff_a'),200,'Same-clinic staff may cancel')['appointment']
        expected={**core(a),'status':'cancelled','revision':2,'cancel_reason':'界'*200,'updated_at_ms':NOW+MINUTE}
        c.require(core(cancelled)==expected,'Cancellation trims Unicode whitespace, counts codepoints and preserves fields')
        c.require(x.ids['slot_a'] in x.free_ids(),'Cancellation reopens future slot')
        newer=x.created('later-booking',actor='patient_b')
        replay=c.response(x.cancel(a['id'],'Different valid reason'),200,'Replay cancelled appointment')['appointment']
        c.require(core(replay)==expected,'Cancellation replay keeps first reason and timestamps')
        c.require(x.ids['slot_a'] not in x.free_ids() and x.detail(newer['id'],'patient_b')['status']=='active','Cancellation replay does not release later booking')
        c.response(x.cancel(a['id'],'   '),400,'Replay still validates reason','invalid_request')
        slot={'id':'duplicate-interval','provider_id':x.ids['provider_a'],'start_ms':a['start_ms']}
        c.response(x.api('POST','/api/slots',slot,actor='staff_a'),409,'Cancelled appointment does not delete slot interval')
        x.s.set_clock(a['start_ms'])
        c.require(core(c.response(x.cancel(a['id']),200,'Past cancelled replay')['appointment'])==expected,'Past cancelled replay stays idempotent')
        c.response(x.cancel(newer['id'],actor='patient_b'),409,'Active cancellation rejects exact start','conflict')
        x.s.restart_backend()
        c.require(core(x.detail(a['id']))==expected and any(r['id']==a['id'] for r in x.history()),'Cancelled record remains durable in history')
    with Case('cancel-races',c) as x:
        a=x.created('race-cancel')
        requests=[{'method':'POST','path':'/api/appointments/'+a['id']+'/cancel','body':{'reason':'Reason '+str(i)},'token':x.tokens['staff_a' if i%2 else 'patient_a']} for i in range(8)]
        values=x.s.parallel_api(requests)
        c.require(all(r['status']==200 for r in values),'Concurrent cancellations complete as replay or first change')
        final=x.detail(a['id'])
        c.require(final['revision']==2 and final['cancel_reason'] in {'Reason '+str(i) for i in range(8)},'Concurrent cancellations retain exactly one first reason')
        c.require(all(core(r['body']['appointment'])==core(final) for r in values),'Concurrent cancellation responses agree on retained record')
        a=x.created('fault-cancel','slot_b')
        x.s.storage_readonly(True)
        failed=x.cancel(a['id'])
        x.s.storage_readonly(False)
        c.response(failed,500,'Storage failure rejects cancellation','storage_error')
        c.require(core(x.detail(a['id']))==core(a) and x.ids['slot_b'] not in x.free_ids(),'Failed cancellation retains record and occupancy')
        c.response(x.cancel(a['id']),200,'Cancellation succeeds after storage recovery')
    with Case('cancel-ui',c) as x:
        a=x.created('ui-cancel')
        x.ui_login('staff_a')
        x.ui('tap',key='nav-appointments')
        x.ui('tap',key='cancel-'+a['id'])
        x.ui('enter_text',key='cancel-reason',text='  ')
        row=x.ui('tap',key='cancel-submit')
        c.require(row['error'] is not None and rendered_status(row,'appointment-'+a['id'],'active') and core(x.detail(a['id']))==core(a),'Invalid cancel UI preserves committed state and shows error')
        x.ui('enter_text',key='cancel-reason',text='  Synthetic appointment change  ')
        row=x.ui('tap',key='cancel-submit')
        c.require(rendered_status(row,'appointment-'+a['id'],'cancelled') and any('Synthetic appointment change' in text for text in row['texts'] if isinstance(text,str)),'Actual cancellation UI retains status and reason')
        c.require(x.detail(a['id'])['status']=='cancelled' and x.ids['slot_a'] in x.free_ids(),'UI cancellation reaches SQLite-backed service')
        x.ui('capture',name='cancelled.png')


def gate_five(c):
    with Case('move',c) as x:
        a=x.created('move-origin')
        occupied=x.created('occupied','slot_d',actor='patient_b')
        for actor in ('patient_b','staff_b'):
            c.require(private_not_found(x.move(a['id'],'m','slot_b',1,actor)) and private_not_found(x.move('missing','m','slot_b',1,actor)),'Move conceals foreign and absent appointment')
        for revision in [True,0,-1,'1',None]:
            c.response(x.move(a['id'],'m','slot_b',revision),400,'Invalid expected revision','invalid_request')
        c.response(x.move(a['id'],'bad key','slot_b',1),400,'Invalid operation id','invalid_request')
        c.response(x.move(a['id'],'m','missing',1),404,'Unknown target slot','not_found')
        for target,revision in [('slot_a',1),('other',1),('foreign',1),('past',1),('edge',1),('slot_d',1),('slot_b',2)]:
            c.response(x.move(a['id'],'m',target,revision),409,'Rejected move target/revision '+target,'conflict')
        c.require(core(x.detail(a['id']))==core(a),'Rejected moves preserve source record')
        x.s.set_clock(NOW+MINUTE)
        moved=c.response(x.move(a['id'],'m','slot_b',1),200,'Failed operation key can later succeed')['appointment']
        expected={**core(a),'slot_id':x.ids['slot_b'],'start_ms':NOW+2*HOUR,'end_ms':NOW+2*HOUR+30*MINUTE,'revision':2,'updated_at_ms':NOW+MINUTE}
        c.require(core(moved)==expected,'Move changes only specified fields and revision')
        c.require(x.ids['slot_a'] in x.free_ids() and x.ids['slot_b'] not in x.free_ids(),'Move atomically transfers availability')
        c.require(core(c.response(x.move(a['id'],'m','slot_b',1),200,'Exact move replay')['appointment'])==expected,'Exact move replay preserves revision')
        c.response(x.move(a['id'],'m','slot_c',1),409,'Replay target cannot change','conflict')
        c.response(x.move(a['id'],'m','slot_b',2),409,'Replay original revision cannot change','conflict')
        another=x.created('other-appointment','slot_a')
        c.response(x.move(another['id'],'m','slot_c',1),409,'Actor replay key scoped across appointments','conflict')
        new=c.response(x.move(a['id'],'m','slot_c',2,actor='staff_a'),200,'Another authorized actor has independent move key')['appointment']
        c.require(new['revision']==3 and new['slot_id']==x.ids['slot_c'],'Staff move accepted with same key in separate actor scope')
        replay=c.response(x.move(a['id'],'m','slot_b',1),200,'Old replay after later move')['appointment']
        c.require(core(replay)==core(new),'Old move replay returns current state without reverting')
        cancelled=c.response(x.cancel(a['id']),200,'Cancellation prerequisite for move replay',prerequisite='RU-004')['appointment']
        c.require(core(c.response(x.move(a['id'],'m','slot_b',1),200,'Move replay after cancellation')['appointment'])==core(cancelled),'Move replay does not reactivate cancelled record')
        c.response(x.move(a['id'],'new-after-cancel','slot_b',4),409,'New move cannot move cancelled appointment','conflict')
        x.s.set_clock(NOW+5*HOUR)
        c.require(core(c.response(x.move(a['id'],'m','slot_b',1),200,'Past move replay')['appointment'])==core(cancelled),'Move replay remains stable after time advances')
        x.s.restart_backend()
        c.require(core(c.response(x.move(a['id'],'m','slot_b',1),200,'Move replay after actual restart')['appointment'])==core(cancelled),'Move replay table durable across restart')
    with Case('move-boundary',c) as x:
        a=x.created('deadline')
        x.s.set_clock(a['start_ms'])
        c.response(x.move(a['id'],'exact-start','slot_b',1),409,'Current appointment exact start cannot move','conflict')
    with Case('move-races',c) as x:
        a=x.created('concurrent')
        request={'method':'POST','path':'/api/appointments/'+a['id']+'/move','body':{'operation_id':'same','to_slot_id':x.ids['slot_b'],'expected_revision':1},'token':x.tokens['patient_a']}
        values=x.s.parallel_api([dict(request) for _ in range(6)])
        c.require(all(r['status']==200 and r['body']['appointment']['revision']==2 for r in values),'Concurrent exact move requests increment once')
        requests=[{**request,'body':{'operation_id':'edit-'+str(i),'to_slot_id':x.ids['slot_c' if i%2 else 'slot_d'],'expected_revision':2}} for i in range(6)]
        values=x.s.parallel_api(requests)
        c.require(sorted(r['status'] for r in values)==[200]+[409]*5,'Concurrent different edits use one expected revision once')
        current=x.detail(a['id'])
        c.require(current['revision']==3,'Concurrent revisions increment only once')
        target='slot_c' if current['slot_id']!=x.ids['slot_c'] else 'slot_d'
        move={'method':'POST','path':'/api/appointments/'+a['id']+'/move','body':{'operation_id':'race-book','to_slot_id':x.ids[target],'expected_revision':3},'token':x.tokens['patient_a']}
        book={'method':'POST','path':'/api/book','body':{'request_id':'race-book','slot_id':x.ids[target]},'token':x.tokens['patient_b']}
        values=x.s.parallel_api([move,book])
        c.require([r['status'] for r in values] in [[200,409],[409,201]],'Move and booking to same target have exactly one winner')
        rows=x.history('staff_a')
        occupied=[r['slot_id'] for r in rows if r['status']=='active']
        c.require(len(occupied)==len(set(occupied)),'Concurrent move/book does not duplicate occupancy')
        current=x.detail(a['id'])
        target=next(key for key in ('slot_a','slot_b','slot_c','slot_d') if x.ids[key] in x.free_ids())
        move={**move,'body':{'operation_id':'race-cancel','to_slot_id':x.ids[target],'expected_revision':current['revision']}}
        cancel={'method':'POST','path':'/api/appointments/'+a['id']+'/cancel','body':{'reason':'Concurrent cancellation'},'token':x.tokens['staff_a']}
        values=x.s.parallel_api([move,cancel])
        c.require(values[0]['status'] in (200,409) and values[1]['status']==200,'Move/cancel statuses follow a legal serial order')
        final=x.detail(a['id'])
        c.require(final['status']=='cancelled' and final['revision'] in (current['revision']+1,current['revision']+2),'Move/cancel produces a single legal cancelled record')
        c.require(final['slot_id'] in x.free_ids(),'Cancelled result owns no slot')
    with Case('move-fault',c) as x:
        a=x.created('fault')
        before=x.free()
        x.s.storage_readonly(True)
        failed=x.move(a['id'],'retry-after-storage','slot_b',1)
        x.s.storage_readonly(False)
        c.response(failed,500,'Read-only store rejects move','storage_error')
        c.require(core(x.detail(a['id']))==core(a) and x.free()==before,'Failed move preserves original and target occupancy')
        c.response(x.move(a['id'],'retry-after-storage','slot_b',1),200,'Failed move key reusable after storage recovery')
    with Case('move-ui',c) as x:
        a=x.created('ui-move')
        x.ui_login('patient_a')
        x.ui('tap',key='nav-appointments')
        x.ui('tap',key='move-'+a['id'])
        row=x.ui('tap',key='move-slot-select')
        c.require(all('move-slot-select-option-'+x.ids[key] not in row['keyed_texts'] for key in ('other','foreign','past','edge')),'Move dropdown offers only future same-provider slots')
        x.ui('tap',key='move-slot-select-option-'+x.ids['slot_b'])
        path='/api/appointments/'+a['id']+'/move'
        x.s.proxy.lose_next(path)
        row=x.ui('tap',key='move-submit')
        c.require(row['error'] is not None and row['error'] in row['texts'],'Lost move reply is visible in real dialog')
        c.require(x.detail(a['id'])['revision']==2,'Lost move response occurs after real commit')
        row=x.ui('tap',key='move-submit')
        c.require(rendered_time(row,'appointment-'+a['id'],NOW+2*HOUR) and row['error'] is None,'Move retry renders server-backed new time')
        requests=[r for r in x.s.proxy.requests if r['path']==path]
        c.require(len(requests)==2 and requests[0]['body']==requests[1]['body'] and requests[1]['body']['expected_revision']==1,'UI retry retains operation and original revision')
        x.ui('tap',key='move-'+a['id'])
        x.ui('select',key='move-slot-select',value=x.ids['slot_c'])
        x.s.proxy.lose_next(path,hold=True)
        row=x.ui('tap',key='move-submit',wait=False)
        c.require(row['busy'] is True,'Pending move represented in real UI')
        x.ui('tap',key='move-submit',wait=False)
        x.s.proxy.release_response()
        row=x.ui('inspect')
        c.require(row['error'] is None and x.detail(a['id'])['revision']==3,'Held double tap produces one committed revision')
        new_requests=[r for r in x.s.proxy.requests if r['path']==path][2:]
        c.require(new_requests and all(r['body']==new_requests[0]['body'] for r in new_requests),'Pending duplicate tap creates no competing move intent')
        x.ui('tap',key='move-'+a['id'])
        x.ui('select',key='move-slot-select',value=x.ids['slot_d'])
        c.response(x.move(a['id'],'concurrent-staff','slot_b',3,actor='staff_a'),200,'Concurrent staff edit before UI submission')
        row=x.ui('tap',key='move-submit')
        c.require(row['error'] is not None and rendered_time(row,'appointment-'+a['id'],NOW+2*HOUR),'Revision conflict refreshes displayed appointment')
        c.require(x.detail(a['id'])['revision']==4,'Stale UI edit does not mutate appointment')
        x.ui('capture',name='rescheduled.png')


GATES=[gate_one,gate_two,gate_three,gate_four,gate_five]


def main():
    results=[]
    infrastructure=[]
    for number,gate in enumerate(GATES,1):
        c=Checks()
        row={'ru_id':f'RU-{number:03d}','gate':gate.__name__,'passed':False}
        try:
            gate(c)
            row.update(passed=True,detail='All associated executable checks passed')
        except PrerequisiteFailure as exc:
            row.update(detail=str(exc),prerequisite_failure=exc.ru)
        except (CandidateFailure,KeyError,IndexError,TypeError) as exc:
            row['detail']=type(exc).__name__+': '+str(exc)
        except Exception as exc:
            row['detail']='Environment/evaluator error: '+repr(exc)
            infrastructure.append({'ru_id':row['ru_id'],'error':repr(exc),'traceback':traceback.format_exc()})
        row['checks_passed']=c.passed
        results.append(row)
    print(json.dumps({'harness_ok':not infrastructure,'results':results,'infrastructure_errors':infrastructure}))
    return 0 if not infrastructure else 2


if __name__=='__main__':
    raise SystemExit(main())
