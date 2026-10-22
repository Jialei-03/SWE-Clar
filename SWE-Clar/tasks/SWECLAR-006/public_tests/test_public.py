"""Published controller/file and actual Flutter widget regression checks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import copy,json
from booking_support import run_session


def seed():
    return {'screens':{'messages':{'title':'Messages','design_ref':'synthetic-messages','platforms':['android','ios']},'home':{'title':'Home','design_ref':'synthetic-home','platforms':['android','ios','web']},'bookings':{'title':'Bookings','design_ref':'synthetic-bookings','platforms':['android','ios','web']}},'users':{'member':{'role':'member'},'guest':{'role':'member'},'manager':{'role':'admin'}},'route':'home','history':[],'bookings':{},'messages':{},'audit':{}}


def action(**values):return {'op':'act','action':values}
def keys(row):return {item['key'] for item in row['controls']}


def required(actual,expected):
    if isinstance(expected,dict):
        assert isinstance(actual,dict)
        for key,value in expected.items():assert key in actual;required(actual[key],value)
    elif isinstance(expected,list):
        assert isinstance(actual,list) and len(actual)==len(expected)
        for left,right in zip(actual,expected):required(left,right)
    else:assert type(actual) is type(expected) and actual==expected


def business(value):
    fields={'screens':['title','design_ref','platforms'],'users':['role'],'bookings':['participants','extension_minutes','extended','confirmed','status'],'messages':['booking_id','sender_id','recipient_id','text'],'audit':['booking_id','actor_id','status']}
    return {'route':value['route'],'history':value['history'],**{group:{key:{field:record[field] for field in names} for key,record in value[group].items()} for group,names in fields.items()}}


def state_matches(actual,expected):
    required(actual,business(expected))
    for collection in ['screens','users','bookings','messages','audit']:
        assert set(actual[collection])==set(expected[collection])



def check_storage():
    initial=seed()
    ops=[{'op':'mutate_initial'},{'op':'mutate_snapshot'},{'op':'mutate_screens'},action(type='create_booking',booking_id='public-a',peer_id='guest'),{'op':'mutate_saved_argument'},{'op':'reopen'},{'op':'fail_storage','value':True},action(type='create_booking',booking_id='public-b',peer_id='guest'),{'op':'fail_storage','value':False},action(type='create_booking',booking_id='public-a',peer_id='guest'),action(type='create_booking',booking_id='empty-peer',peer_id='missing'),action(type='create_booking',booking_id='self-peer',peer_id='member'),action(type='create_booking',booking_id='  ',peer_id='guest')]
    result=run_session(ops,initial=initial);rows=result['observations']
    for row in rows[:3]:state_matches(row['snapshot'],initial)
    expected=copy.deepcopy(initial);expected['bookings']['public-a']={'participants':['member','guest'],'extension_minutes':0,'extended':False,'confirmed':False,'status':'draft'}
    assert rows[3]['accepted'] is True and rows[3]['action_unchanged'] is True
    for row in rows[3:]:
        state_matches(row['snapshot'],expected)
    assert rows[7]['accepted'] is False and rows[7]['error']=='storage_failed'
    for row in rows[9:]:assert row['accepted'] is False and row['error']=='invalid_booking'
    state_matches(result['persisted_state'],expected)


def check_pending_save():
    initial=seed();op={'type':'create_booking','booking_id':'held','peer_id':'guest'}
    result=run_session([{'op':'hold_storage'},{'op':'begin_act','action':op},action(type='create_booking',booking_id='concurrent',peer_id='guest'),{'op':'finish_act'},{'op':'restore'}],initial=initial)
    rows=result['observations'];assert rows[1]['busy'] is True and rows[1]['writes']==0;state_matches(rows[1]['snapshot'],initial)
    assert rows[2]['accepted'] is False and rows[2]['writes']==0;state_matches(rows[2]['snapshot'],initial)
    assert rows[3]['accepted'] is True and rows[3]['busy'] is False and rows[3]['writes']==1
    assert set(rows[4]['snapshot']['bookings'])=={'held'};state_matches(result['persisted_state'],rows[4]['snapshot'])


def check_widgets():
    operations=[]
    for index,width in enumerate([360,768]):
        operations += [{'op':'viewport','width':width,'height':950},{'op':'mount'},{'op':'tap','key':'nav-bookings'},{'op':'enter_text','key':'booking-id','text':f'ui-{index}'},{'op':'tap','key':'create'},{'op':'inspect'},{'op':'tap','key':'nav-home'}]
    result=run_session(operations,initial=seed());rows=result['observations']
    for offset in [0,7]:
        assert {'nav-home','nav-bookings','nav-messages'}<=keys(rows[offset+1])
        row=rows[offset+5];index=offset//7
        assert f'booking-ui-{index}' in keys(row) and f'status-ui-{index}' in keys(row)
        assert any(f'ui-{index}' in value for value in row['texts'] if value is not None)
    web=run_session([{'op':'mount'},action(type='navigate',screen_id='messages')],initial=seed(),platform='web')['observations']
    assert [row['screen_id'] for row in web[0]['screens']]==['bookings','home']
    assert 'nav-messages' not in keys(web[0]) and web[1]['accepted'] is False and web[1]['error']=='unknown_screen'


if __name__=='__main__':
    results=[]
    for name,check in [('state_and_file_isolation',check_storage),('pending_save_atomicity',check_pending_save),('real_widgets_and_platforms',check_widgets)]:
        try:check();results.append({'check':name,'passed':True})
        except Exception as error:results.append({'check':name,'passed':False,'detail':type(error).__name__+': '+str(error)})
    print(json.dumps({'passed':all(row['passed'] for row in results),'checks':results}))
    raise SystemExit(0 if all(row['passed'] for row in results) else 1)
