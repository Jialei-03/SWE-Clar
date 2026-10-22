"""Protected independent business assertions over the public Flutter operation transport."""
import copy,json,sys,traceback
sys.path.insert(0,'/public_tests')
from booking_support import run_session,CandidateFailure
from test_public import seed,action,keys,required,state_matches,business,check_storage,check_pending_save,check_widgets


def initial_bookings():
    initial=seed();initial['users']['observer']={'role':'member'}
    initial['bookings']['booking-a']={'participants':['member','guest'],'extension_minutes':0,'extended':False,'confirmed':False,'status':'draft'}
    return initial


def unchanged(row,prior,error):
    assert row['accepted'] is False and row['error']==error
    state_matches(row['snapshot'],prior)


def check_1():
    check_storage();check_pending_save()
    probe=run_session([{'op':'file_storage_probe'}],initial=seed())['observations'][0]
    assert probe['previous_bytes_preserved'], 'File save overwrote the previously published inode'
    state_matches(probe['loaded'],probe['expected'])
    assert sorted(probe['siblings'])==['previous.json','state.json'], 'Successful save left temporary siblings'
    initial=seed()
    rows=run_session([{'op':'restore'},action(type='unknown'),action(type='create_booking',booking_id='ok',peer_id='guest')],initial=initial)['observations']
    state_matches(rows[0]['snapshot'],initial);unchanged(rows[1],initial,'unknown_action');assert rows[2]['accepted'] is True and rows[2]['error'] is None
    unknown=run_session([action(type='create_booking',booking_id='x',peer_id='guest')],initial=initial,actor='missing')['observations'][0]
    unchanged(unknown,initial,'unknown_actor')


def check_2():
    check_widgets()
    initial=seed();initial['screens']['bookings']['title']='Local appointments'
    ops=[{'op':'mount'},{'op':'tap','key':'nav-bookings'},{'op':'fail_storage','value':True},{'op':'tap','key':'create'},{'op':'inspect'},{'op':'fail_storage','value':False},{'op':'tap','key':'create'},{'op':'reopen'}]
    result=run_session(ops,initial=initial,platform='ios');rows=result['observations']
    assert 'Local appointments' in rows[0]['texts']
    assert rows[4]['error']=='storage_failed' and rows[4]['snapshot']['bookings']=={} and 'booking-sample-booking' not in keys(rows[4])
    assert 'error' in keys(rows[4]) and 'storage_failed' in rows[4]['texts']
    assert 'booking-sample-booking' in keys(rows[7]) and rows[7]['error'] is None
    state_matches(result['persisted_state'],rows[7]['snapshot'])


def check_3():
    initial=seed();initial['route']='bookings';initial['history']=['home','messages','retired-screen']
    ops=[{'op':'mount'},{'op':'tap','key':'back'},action(type='navigate',screen_id='home'),{'op':'tap','key':'nav-bookings'},{'op':'tap','key':'nav-bookings'},action(type='navigate',screen_id='missing'),action(type='navigate',screen_id='messages'),{'op':'fail_storage','value':True},action(type='back'),{'op':'fail_storage','value':False},{'op':'reopen'},{'op':'tap','key':'back'},action(type='back'),{'op':'reopen'}]
    result=run_session(ops,initial=initial,platform='web');rows=result['observations']
    assert rows[1]['snapshot']['route']=='home' and rows[1]['snapshot']['history']==[] and 'create' not in keys(rows[1])
    assert rows[2]['accepted'] is True and rows[2]['snapshot']['history']==[]
    for i in [3,4,10]:
        assert rows[i]['snapshot']['route']=='bookings' and rows[i]['snapshot']['history']==['home'] and 'create' in keys(rows[i])
    for i in [5,6]:unchanged(rows[i],rows[4]['snapshot'],'unknown_screen')
    unchanged(rows[8],rows[4]['snapshot'],'storage_failed')
    for i in [11,12,13]:assert rows[i]['snapshot']['route']=='home' and rows[i]['snapshot']['history']==[]
    assert rows[12]['accepted'] is True
    state_matches(result['persisted_state'],rows[13]['snapshot'])
    # Several valid pages use a real LIFO stack and survive reopening.
    regular=run_session([{'op':'mount'},{'op':'tap','key':'nav-bookings'},{'op':'tap','key':'nav-messages'},{'op':'reopen'},{'op':'tap','key':'back'},{'op':'tap','key':'back'}],initial=seed())['observations']
    assert regular[3]['snapshot']['route']=='messages' and regular[3]['snapshot']['history']==['home','bookings']
    assert regular[4]['snapshot']['route']=='bookings' and regular[4]['snapshot']['history']==['home']
    assert regular[5]['snapshot']['route']=='home' and regular[5]['snapshot']['history']==[]


def check_4():
    initial=initial_bookings()
    ops=[];invalid_indices=[]
    for value in [0,31,True,1.5,'5',None,-2]:
        invalid_indices.append(len(ops));ops.append(action(type='extend',booking_id='booking-a',minutes=value))
    ops += [action(type='extend',booking_id='missing',minutes=5),action(type='extend',booking_id='booking-a',minutes=1),action(type='extend',booking_id='booking-a',minutes=2),action(type='confirm',booking_id='booking-a'),action(type='confirm',booking_id='booking-a'),action(type='extend',booking_id='booking-a',minutes=1),{'op':'reopen'}]
    rows=run_session(ops,initial=initial)['observations']
    for i in invalid_indices+[7]:unchanged(rows[i],initial,'extension_denied')
    assert rows[8]['accepted'] is True
    required(rows[8]['snapshot']['bookings']['booking-a'],{'extension_minutes':1,'extended':True,'confirmed':False,'status':'draft'})
    unchanged(rows[9],rows[8]['snapshot'],'extension_denied');assert rows[10]['accepted'] is True
    required(rows[10]['snapshot']['bookings']['booking-a'],{'extension_minutes':1,'extended':True,'confirmed':True,'status':'confirmed'})
    unchanged(rows[11],rows[10]['snapshot'],'confirmation_denied');unchanged(rows[12],rows[10]['snapshot'],'extension_denied')
    state_matches(rows[13]['snapshot'],rows[10]['snapshot'])
    # Permission and lifecycle cases are constructed directly, independently of admin implementation.
    restricted=initial_bookings()
    for status in ['confirmed','cancelled','completed']:
        restricted['bookings'][status]={**copy.deepcopy(restricted['bookings']['booking-a']),'status':status,'confirmed':status!='cancelled'}
    denied=[]
    for name in ['booking-a','confirmed','cancelled','completed','missing']:
        denied += [action(type='extend',booking_id=name,minutes=5,actor_id='member',role='admin'),action(type='confirm',booking_id=name,actor_id='member',role='admin')]
    foreign=run_session(denied,initial=restricted,actor='observer')['observations']
    for i,row in enumerate(foreign):unchanged(row,restricted,'extension_denied' if i%2==0 else 'confirmation_denied')
    terminal=[]
    for name in ['confirmed','cancelled','completed']:terminal += [action(type='extend',booking_id=name,minutes=5),action(type='confirm',booking_id=name)]
    for i,row in enumerate(run_session(terminal,initial=restricted)['observations']):unchanged(row,restricted,'extension_denied' if i%2==0 else 'confirmation_denied')
    # Guest participant can complete the actual controls; outsider and admin views differ.
    ui_initial=initial_bookings();ui_initial['route']='bookings'
    ui=run_session([{'op':'mount'},{'op':'enter_text','key':'minutes','text':'30'},{'op':'tap','key':'extend-booking-a'},{'op':'tap','key':'confirm-booking-a'},{'op':'reopen'},{'op':'switch_actor','actor':'observer','mount':True},{'op':'switch_actor','actor':'manager','mount':True},action(type='confirm',booking_id='booking-a')],initial=ui_initial,actor='guest')['observations']
    required(ui[2]['snapshot']['bookings']['booking-a'],{'extension_minutes':30,'extended':True})
    assert '30' in ' '.join(ui[2]['keyed_texts']['status-booking-a']) and 'draft' in ' '.join(ui[2]['keyed_texts']['status-booking-a'])
    assert 'confirmed' in ' '.join(ui[4]['keyed_texts']['status-booking-a']) and '30' in ' '.join(ui[4]['keyed_texts']['status-booking-a'])
    assert 'booking-booking-a' not in keys(ui[5]) and 'booking-booking-a' in keys(ui[6])
    assert ui[7]['accepted'] is False and ui[7]['error']=='confirmation_denied'
    # Confirmation before an extension is a valid alternative path.
    first=run_session([action(type='confirm',booking_id='booking-a')],initial=initial)['observations'][0]
    assert first['accepted'] is True;required(first['snapshot']['bookings']['booking-a'],{'extension_minutes':0,'extended':False,'confirmed':True,'status':'confirmed'})


def check_5():
    initial=initial_bookings();body='  <b>Literal & note</b> · café  '
    message={'type':'message','booking_id':'booking-a','message_id':'message-a','recipient_id':'guest','text':body}
    invalid=[]
    for override in [{'recipient_id':'member'},{'recipient_id':'observer'},{'recipient_id':'missing'},{'message_id':''},{'message_id':'  '},{'message_id':2},{'text':' \t '},{'text':7},{'booking_id':'missing'}]:invalid.append(action(**{**message,**override}))
    ops=invalid+[action(**message),action(**{**message,'ignored_metadata':1}),action(**{**message,'text':'Different'}),action(type='admin_status',booking_id='booking-a',event_id='forged',status='completed',actor_id='manager',role='admin'),{'op':'reopen'}]
    result=run_session(ops,initial=initial);rows=result['observations']
    for row in rows[:len(invalid)]:unchanged(row,initial,'message_denied')
    accepted=rows[len(invalid)];assert accepted['accepted'] is True
    assert set(accepted['snapshot']['messages'])=={'message-a'}
    required(accepted['snapshot']['messages']['message-a'],{'booking_id':'booking-a','sender_id':'member','recipient_id':'guest','text':body})
    assert rows[len(invalid)+1]['accepted'] is True
    unchanged(rows[len(invalid)+2],accepted['snapshot'],'message_conflict');unchanged(rows[len(invalid)+3],accepted['snapshot'],'admin_required')
    state_matches(result['persisted_state'],rows[-1]['snapshot'])
    # Reordered stored fields and extra metadata must not invalidate a semantic replay.
    replay=copy.deepcopy(initial);replay['messages']['message-a']={'text':body,'recipient_id':'guest','sender_id':'member','booking_id':'booking-a','note':'harmless'}
    same=run_session([action(**message)],initial=replay)['observations'][0];assert same['accepted'] is True
    outsider=run_session([action(**message)],initial=initial,actor='observer')['observations'][0];unchanged(outsider,initial,'message_denied')
    # Real message composition and recipient-only rendering, then an independent file reload.
    ui=copy.deepcopy(initial);ui['route']='messages'
    ui_ops=[{'op':'mount'},{'op':'enter_text','key':'chat-booking','text':'booking-a'},{'op':'enter_text','key':'message','text':body},{'op':'tap','key':'send'},{'op':'reopen'},{'op':'switch_actor','actor':'guest','mount':True},{'op':'switch_actor','actor':'observer','mount':True},{'op':'switch_actor','actor':'manager','mount':True}]
    ui_result=run_session(ui_ops,initial=ui);observed=ui_result['observations']
    for i in [3,4,5]:assert body in observed[i]['texts'] and any(key.startswith('message-') for key in keys(observed[i]))
    for i in [6,7]:assert body not in observed[i]['texts'] and not any(key.startswith('message-') for key in keys(observed[i]))
    assert len(ui_result['persisted_state']['messages'])==1
    # Admin overrides and replay are independently checked from participant behavior.
    admin=initial_bookings();admin['bookings']['booking-a']['extension_minutes']=8;admin['bookings']['booking-a']['extended']=True
    events=[action(type='admin_status',booking_id='booking-a',event_id='event-a',status='confirmed'),action(type='admin_status',booking_id='booking-a',event_id='event-b',status='cancelled'),action(type='admin_status',booking_id='booking-a',event_id='event-a',status='confirmed'),action(type='admin_status',booking_id='booking-a',event_id='event-a',status='completed'),action(type='admin_status',booking_id='booking-a',event_id='event-c',status='draft'),action(type='admin_status',booking_id='booking-a',event_id='event-d',status='completed')]
    invalid_events=[action(type='admin_status',booking_id='booking-a',event_id='  ',status='draft'),action(type='admin_status',booking_id='missing',event_id='new',status='draft'),action(type='admin_status',booking_id='booking-a',event_id='new',status='unknown')]
    output=run_session(events+invalid_events+[{'op':'fail_storage','value':True},action(type='admin_status',booking_id='booking-a',event_id='failed',status='draft'),{'op':'fail_storage','value':False},{'op':'reopen'}],initial=admin,actor='manager');ar=output['observations']
    for i,status,confirmed in [(0,'confirmed',True),(1,'cancelled',False),(2,'cancelled',False),(4,'draft',False),(5,'completed',True)]:
        assert ar[i]['accepted'] is True;required(ar[i]['snapshot']['bookings']['booking-a'],{'status':status,'confirmed':confirmed,'extension_minutes':8,'extended':True})
    assert set(ar[2]['snapshot']['audit'])=={'event-a','event-b'};unchanged(ar[3],ar[2]['snapshot'],'event_conflict')
    for row in ar[6:9]:unchanged(row,ar[5]['snapshot'],'invalid_status')
    unchanged(ar[10],ar[5]['snapshot'],'storage_failed');state_matches(output['persisted_state'],ar[5]['snapshot'])
    for event in ar[5]['snapshot']['audit'].values():assert event['actor_id']=='manager' and event['booking_id']=='booking-a'
    reordered=copy.deepcopy(admin);reordered['audit']['same']={'status':'completed','actor_id':'manager','booking_id':'booking-a','note':'harmless'}
    event=run_session([action(type='admin_status',booking_id='booking-a',event_id='same',status='completed')],initial=reordered,actor='manager')['observations'][0]
    assert event['accepted'] is True and event['snapshot']['bookings']['booking-a']['status']=='draft'
    # Fresh actual admin intents remain distinct across component reopening.
    admin_ui=initial_bookings();admin_ui['route']='bookings';admin_ui['bookings']['booking-b']=copy.deepcopy(admin_ui['bookings']['booking-a'])
    au=run_session([{'op':'mount'},{'op':'tap','key':'complete-booking-a'},{'op':'reopen'},{'op':'tap','key':'complete-booking-b'},{'op':'reopen'}],initial=admin_ui,actor='manager')['observations']
    assert len(au[-1]['snapshot']['audit'])==2
    for booking in au[-1]['snapshot']['bookings'].values():required(booking,{'status':'completed','confirmed':True})


if __name__=='__main__':
    results=[];infrastructure=[]
    for number,check in enumerate([check_1,check_2,check_3,check_4,check_5],1):
        try:check();results.append({'ru_id':f'RU-{number:03d}','passed':True})
        except (AssertionError,KeyError,TypeError,ValueError) as error:
            results.append({'ru_id':f'RU-{number:03d}','passed':False,'detail':type(error).__name__+': '+str(error)});traceback.print_exc(file=sys.stderr)
        except Exception as error:
            infrastructure.append(type(error).__name__+': '+str(error));traceback.print_exc(file=sys.stderr)
    print(json.dumps({'harness_ok':not infrastructure,'results':results,'infrastructure_errors':infrastructure}))
    raise SystemExit(2 if infrastructure else 0)
