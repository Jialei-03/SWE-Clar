"""Independent lifecycle and real SQLite checks; no candidate import in evaluator."""
from pathlib import Path
import json,subprocess,sys,tempfile
from candidate_proxy import call,cli
from test_solution import base,active,paid
from types import SimpleNamespace
M=SimpleNamespace(process_review_action=call)

def ru001():
    # Every call is a new process. Later seed data cannot replace committed state.
    with tempfile.TemporaryDirectory(prefix='review-ledger-') as directory:
        root=Path(directory);root.chmod(0o777);database=root/'ledger.db'
        try:
            seed=base()
            first=cli({'seed':seed,'action':{'type':'create_listing','listing_id':'persist','owner_id':'l','price':10}},database)
            assert 'persist' in first['listings']
            denied=cli({'seed':{},'action':{'type':'accept','application_id':'missing','owner_id':'l'}},database)
            assert denied.get('error',{}).get('code')
            second=cli({'seed':{},'action':{'type':'profile_image','user_id':'r','image_ref':'updated'}},database)
            assert second['listings']==first['listings'] and second['users']['l']==seed['users']['l']
            assert second['users']['r']['profile_image']=='updated'
            code="import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); assert c.execute('PRAGMA integrity_check').fetchone()==('ok',)"
            subprocess.run([sys.executable,'-I','-c',code,str(database)],check=True,user=1000,group=1000,extra_groups=[])
        finally:
            subprocess.run([sys.executable,'-I','-c',"from pathlib import Path;import sys;[p.unlink() for p in Path(sys.argv[1]).iterdir()]",str(root)],check=True,user=1000,group=1000,extra_groups=[])

def ru002():
    state=call(base(),{'type':'create_listing','listing_id':'x','owner_id':'l','price':100})
    assert 'error' in call(state,{'type':'apply','application_id':'self','listing_id':'x','reviewer_id':'l'})
    state=call(state,{'type':'apply','application_id':'a','listing_id':'x','reviewer_id':'r'})
    assert 'error' in call(state,{'type':'accept','application_id':'a','owner_id':'r'})
    state=call(state,{'type':'accept','application_id':'a','owner_id':'l'})
    assert state['listings']['x']['active_review_id']=='a' and state['reviews']['a']['reviewer_id']=='r'

def ru003():
    for images in [[],['asset'],['a','b','c','d','e']]:
        state=paid(M)
        result=call(state,{'type':'submit_review','review_id':'a','reviewer_id':'r','images':images})
        assert result['reviews']['a']['status']=='submitted' and result['reviews']['a']['images']==images
        assert result['result']['url_skipped'] is True
    assert 'error' in call(paid(M),{'type':'submit_review','review_id':'a','reviewer_id':'l','images':[]})

def fresh_payment_rejections(state,invoke):
    for amount in [99.99,100.01]:
        rejected=invoke(state,{'type':'payment','event_id':f'fresh-{amount}','listing_id':'x','payer_id':'l','amount':amount})
        assert isinstance(rejected.get('error',{}).get('code'),str) and rejected['error']['code']
        for key in ['users','sessions','fee_rate','listings','applications','reviews']:
            if key in state:assert rejected[key]==state[key]
        for key,empty in [('payments',{}),('processed_events',[]),('payouts',[])]:
            assert rejected.get(key,empty)==state.get(key,empty)

def ru004():
    fresh_payment_rejections(active(M),call)
    for gross,rate,fee,eligible in [(0.1,0.15,0.02,0.08),(1.05,0.1,0.11,0.94),(20,0,0,20),(20,1,20,0)]:
        seed=base();seed['fee_rate']=rate
        state=call(seed,{'type':'create_listing','listing_id':'x','owner_id':'l','price':gross})
        state=call(state,{'type':'apply','application_id':'a','listing_id':'x','reviewer_id':'r'})
        state=call(state,{'type':'accept','application_id':'a','owner_id':'l'})
        payment={'type':'payment','event_id':'p','listing_id':'x','payer_id':'l','amount':gross,'payment_secret':'synthetic-credential-must-not-leak'}
        assert 'error' in call(state,{**payment,'payer_id':'r'})
        state=call(state,payment);saved=state['payments']['p']
        assert (saved['platform_fee'],saved['eligible'],saved['receiver_id'],saved['listing_id'])==(fee,eligible,'r','x')
        assert 'synthetic-credential-must-not-leak' not in json.dumps(state)
        assert call(state,payment)['payments']==state['payments']
        assert 'error' in call(state,{**payment,'amount':gross+1})
        assert 'error' in call(state,{**payment,'event_id':'second'})
        assert state['listings']['x']['status']=='in_review'
        state=call(state,{'type':'submit_review','review_id':'a','reviewer_id':'r','images':[]})
        assert 'error' in call(state,{'type':'approve_review','listing_id':'x','owner_id':'r'})
        state=call(state,{'type':'approve_review','listing_id':'x','owner_id':'l'})
        again=call(state,{'type':'approve_review','listing_id':'x','owner_id':'l'})
        assert len(again['payouts'])==1 and again['payouts'][0]['event_id']=='p' and again['payouts'][0]['amount']==eligible
        assert again['listings']['x']['status']=='completed' and again['payments']['p']['status']=='released'

def ru005():
    state=base();state['sessions']=['r']
    for action in [{'type':'delete_account','user_id':'l'},{'type':'profile_image','user_id':'l','image_ref':'changed'}]:
        assert 'error' in call(state,action)
    changed=call(state,{'type':'delete_account','user_id':'r'})
    assert changed['users']=={'l':state['users']['l']} and changed['sessions']==[]
