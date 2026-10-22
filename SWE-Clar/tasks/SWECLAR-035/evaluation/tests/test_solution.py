"""Behavioral RU checks with independent public-schema seeds."""
from copy import deepcopy
from candidate_proxy import call


def state(paid=False):
    return {'users':{'u':{'email':'member@example.org','phone':'synthetic-contact','provider':'email','status':'active','membership':'paid' if paid else 'free','credits':4}},'products':{'a':{'price_tl':17,'credits':3},'b':{'price_tl':11,'credits':2}},'coupons':{'partial':{'active':True,'amount_tl':5},'zero':{'active':True,'amount_tl':100},'disabled':{'active':False,'amount_tl':100}},'carts':{},'orders':{},'ledger':[],'payments':[],'unrelated':{'nested':[1,2]}}


def business(s):return {k:v for k,v in s.items() if k not in ('result','error')}


def subset(actual,expected):
    assert isinstance(actual,dict)
    for k,v in expected.items():assert actual.get(k)==v,(k,actual.get(k),v)


def order_seed(total=9,currency='credits',credits=4):
    s=state(currency=='credits');s['users']['u']['credits']=credits
    s['orders']['o']={'user_id':'u','total':total,'currency':currency,'kind':'regular','status':'pending','thank_you':'credit' if currency=='credits' else 'regular','payment_required':currency=='TL' and total>0}
    return s


def test_ru_001_contract():
    s={'unrelated':{'nested':['retain']}}
    a={'type':'create_account','user_id':'u','email':'member@example.org','provider':'email','card':{'number':'sensitive-synthetic-pan','security_code':'sensitive-synthetic-cvv'}}
    result=call(s,a);assert result==call(s,a)
    assert result['unrelated']==s['unrelated']
    def leaves(value):
        if isinstance(value,dict):return [x for v in value.values() for x in leaves(v)]
        if isinstance(value,list):return [x for v in value for x in leaves(v)]
        return [value]
    assert not {'sensitive-synthetic-pan','sensitive-synthetic-cvv'}.intersection(str(v) for v in leaves(result))
    s=state();s.update(result={'obsolete':True},error={'code':'old'})
    result=call(s,{'type':'delete_account','user_id':'u'})
    assert 'error' not in result and result.get('result',{}).get('obsolete') is None


def test_ru_002_accounts():
    for provider in ['email','social','fast_checkout']:
        a={'type':'create_account','user_id':'new-user','provider':provider,'email':'Mixed@example.org','phone':'contact-one'}
        first=call(state(),a);account=first['users']['new-user']
        subset(account,{'status':'active','membership':'free','credits':0})
        next_state=call(first,dict(a,email='other@example.org',phone='contact-two'))
        assert next_state['users']['new-user']['email'].casefold()==a['email'].casefold()
        assert next_state['users']['new-user']['phone']==a['phone']
        assert len(next_state['users'])==2
        deleted=call(next_state,{'type':'delete_account','user_id':'new-user'})
        assert deleted['users']['new-user']['status']=='inactive'
        assert call(deleted,a)['users']['new-user']['status']=='inactive'


def test_ru_003_prices():
    items=[{'product_id':'a','quantity':2,'price_tl':1,'credits':1},{'product_id':'b','quantity':3}]
    for paid,total,currency in [(False,67,'TL'),(True,12,'credits')]:
        s=state(paid);r=call(s,{'type':'set_cart','user_id':'u','items':items})
        for cart in [r['result'],r['carts']['u']]:
            subset(cart,{'total':total,'currency':currency,'coupon_visible':not paid})
            assert len(cart['items'])==2
            for actual,item in zip(cart['items'],items):subset(actual,{'product_id':item['product_id'],'quantity':item['quantity']})
        assert r['products']==s['products'] and r['unrelated']==s['unrelated']


def test_ru_001_reject():
    for bad in ['missing_product','inactive_product','zero_quantity','negative_quantity','inactive_user','missing_user']:
        s=state();a={'type':'set_cart','user_id':'u','items':[{'product_id':'a','quantity':1}]}
        if bad=='missing_product':a['items'][0]['product_id']='absent'
        elif bad=='inactive_product':s['products']['a']['active']=False
        elif bad=='zero_quantity':a['items'][0]['quantity']=0
        elif bad=='negative_quantity':a['items'][0]['quantity']=-1
        elif bad=='inactive_user':s['users']['u']['status']='inactive'
        else:a['user_id']='absent'
        r=call(s,a);assert isinstance(r.get('error',{}).get('code'),str) and r['error']['code']
        assert business(r)==business(s)


def test_ru_004_routes():
    for paid,coupon,kind,total,route in [(False,None,'regular',17,'regular'),(False,'partial','regular',12,'regular'),(False,'zero','regular',0,'coupon'),(False,'disabled','regular',17,'regular'),(False,'unknown','regular',17,'regular'),(True,'zero','regular',3,'credit'),(False,None,'membership',17,'membership')]:
        s=state(paid);s['carts']['u']={'items':[{'product_id':'a','quantity':1}],'total':3 if paid else 17,'currency':'credits' if paid else 'TL','coupon_visible':not paid}
        a={'type':'checkout','user_id':'u','order_id':'o','kind':kind}
        if coupon:a['coupon_code']=coupon
        r=call(s,a);subset(r['result'],{'order_id':'o','thank_you':route,'payment_required':not paid and total>0})
        subset(r['orders']['o'],{'total':total,'currency':'credits' if paid else 'TL','status':'pending','user_id':'u'})
        changed=deepcopy(r);changed['carts']['u']['total']=999
        repeated=call(changed,a);assert repeated['orders']==r['orders']


def test_ru_004_settlement_replay():
    for total in [0,23]:
        s=order_seed(total,'TL');a={'type':'settle','order_id':'o','event_id':'event-one'}
        r=call(s,a);assert r['orders']['o']['status']=='settled'
        assert len(r['ledger'])==1;subset(r['ledger'][0],{'kind':'settlement','order_id':'o','event_id':'event-one'})
        assert len(r['payments'])==(1 if total else 0)
        if total:subset(r['payments'][0],{'kind':'regular_payment','order_id':'o','event_id':'event-one','amount_tl':total})
        assert business(call(r,a))==business(r)
        assert business(call(r,dict(a,event_id='different-event')))==business(r)
        r['orders']['other']=deepcopy(s['orders']['o'])
        assert business(call(r,dict(a,order_id='other')))==business(r)


def test_ru_001_missing_cart_and_order():
    s=state()
    for a in [{'type':'checkout','user_id':'u','order_id':'o'},{'type':'settle','order_id':'absent','event_id':'e'}]:
        r=call(s,a);assert r.get('error',{}).get('code');assert business(r)==business(s)

def test_ru_001_commerce_requires_active_user():
    for status in ('missing','inactive'):
        for kind in ('checkout','settle','renew'):
            s=order_seed(total=9,currency='credits')
            s['carts']['u']={'items':[{'product_id':'a','quantity':1}],'total':3,'currency':'credits','coupon_visible':False}
            if status=='missing':del s['users']['u']
            else:s['users']['u']['status']='inactive'
            actions={'checkout':dict(type='checkout',user_id='u',order_id='new'),
                     'settle':dict(type='settle',order_id='o',event_id='settle-invalid-user'),
                     'renew':dict(type='renew',user_id='u',event_id='renew-invalid-user',date='2030-06-02',new_expiry='2030-07-02',package_credits=5)}
            out=call(s,actions[kind])
            assert isinstance(out.get('error',{}).get('code'),str) and out['error']['code']
            assert business(out)==business(s)


def test_ru_005_shortfall():
    for credits,total in [(4,9),(9,9),(12,9),(0,7)]:
        s=order_seed(total,credits=credits);a={'type':'settle','order_id':'o','event_id':'settle-event'}
        r=call(s,a);assert r['users']['u']['credits']==max(0,credits-total)
        assert len(r['payments'])==(1 if credits<total else 0)
        if credits<total:subset(r['payments'][0],{'kind':'saved_payment_topup','order_id':'o','event_id':'settle-event','credits':total-credits})
        assert business(call(r,a))==business(r)
        assert business(call(r,dict(a,event_id='new-settle-event')))==business(r)


def test_ru_005_renewal():
    for expiry,expected in [('2030-06-01',5),('2030-06-02',5),('2030-06-03',12),(None,12)]:
        s=state(True);s['users']['u']['credits']=7
        if expiry:s['users']['u']['credit_expiry']=expiry
        a={'type':'renew','user_id':'u','event_id':'renew-event','date':'2030-06-02','new_expiry':'2030-07-02','package_credits':5}
        r=call(s,a);subset(r['users']['u'],{'credits':expected,'credit_expiry':'2030-07-02','membership':'paid'})
        assert len(r['ledger'])==1;subset(r['ledger'][0],{'kind':'renewal','event_id':'renew-event','user_id':'u'})
        assert business(call(r,a))==business(r)


def test_ru_001_cli():
    from candidate_proxy import cli
    request={'state':{},'action':{'type':'create_account','user_id':'cli-user','email':'cli@example.org','provider':'email'}}
    result=cli(request)
    assert result['users']['cli-user']['email'].casefold()=='cli@example.org'


def test_ru_005_free_membership_renewal():
 s=state(False)
 out=call(s,{'type':'renew','user_id':'u','event_id':'free-renewal','date':'2030-06-02','new_expiry':'2030-07-02','package_credits':5})
 assert 'error' not in out and out['users']['u']['membership']=='paid'
