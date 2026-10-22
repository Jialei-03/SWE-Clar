from copy import deepcopy
import math
from candidate_proxy import call,cli

def base():return {'products':{'p':{'names':{'de':'Kraeuter Pizza','en':'Herb pizza'},'price':12.25,'active':True},'s':{'names':{'de':'Salat','en':'Salad'},'price':7.5,'active':True},'hidden':{'names':{},'price':-1,'active':False}},'customers':{'c':{'points':500},'other':{'points':0}},'coupons':{'SAVE':{'active':True,'percent':12.5},'OLD':{'active':False,'percent':20}},'zones':{'near':{'enabled':True,'minimum':30},'far':{'enabled':False,'minimum':0}},'admins':['admin'],'carts':{},'orders':{},'reservations':{}}
def withcart():
 s=base();s['carts']['c']={'items':[{'product_id':'p','quantity':2},{'product_id':'s','quantity':1}],'subtotal':32};return s
def orderstate():
 s=withcart();s['orders']['o']={'customer_id':'c','mode':'pickup','subtotal':32,'total':25.5,'coupon_code':'SAVE','redeemed_points':250,'paid':False,'status':'pending'};return s
def same(a,b):
 for k in ['products','customers','coupons','zones','admins','carts','orders','reservations']:
  assert a.get(k)==b.get(k),k
def ok(s,a):
 out=call(s,a);assert 'error' not in out,out;return out
def denied(s,a):
 out=call(s,a);assert out.get('error',{}).get('code');same(out,s);return out
def checkout(**kw):return {'type':'checkout','customer_id':'c','order_id':'o','mode':'pickup','coupon_code':'SAVE','redeem_points':250,**kw}
def rows(r):
 assert all(x['returncode']==0 and isinstance(x['output'],dict) for x in r),r
 return [x['output'] for x in r]

def cart_quantities(items):
 totals={}
 for item in items:
  quantity=item['quantity'];assert isinstance(quantity,int) and not isinstance(quantity,bool) and quantity>0
  totals[item['product_id']]=totals.get(item['product_id'],0)+quantity
 return totals

def test_ru_001_entry():
 s=base();r=ok(s,dict(type='catalog',language='en'));same(s,r);denied(s,{'type':'unknown'});denied(s,{})
 obs=rows(cli(s,[{'command':'act','value':dict(type='catalog',language='en')},{'command':'show'},{'command':'act','value':[]},{'command':'show'}]));assert 'products' in obs[2].get('result',{});assert obs[3]['error']['code'];assert obs[2]==obs[4]

def test_ru_002_catalog_cart():
 s=base()
 for lang,names in [('en',{'Herb pizza','Salad'}),('de',{'Kraeuter Pizza','Salat'})]:
  entries=ok(s,dict(type='catalog',language=lang))['result']['products'];assert {x['name'] for x in entries}==names and {x['product_id'] for x in entries}=={'p','s'}
 denied(s,dict(type='catalog',language='xx'))
 bad=deepcopy(s);bad['products']['p']['names']['de']='';denied(bad,dict(type='catalog',language='en'))
 action=dict(type='set_cart',customer_id='c',items=[{'product_id':'p','quantity':1,'price':0},{'product_id':'p','quantity':1},{'product_id':'s','quantity':1}],subtotal=999,total=0);out=ok(s,action);assert math.isclose(out['result']['subtotal'],32) and math.isclose(out['carts']['c']['subtotal'],32)
 assert cart_quantities(out['carts']['c']['items'])=={'p':2,'s':1}
 for items in [[{'product_id':'p','quantity':0}],[{'product_id':'p','quantity':True}],[{'product_id':'hidden','quantity':1}],[{'product_id':'missing','quantity':1}]]:denied(out,dict(type='set_cart',customer_id='c',items=items))
 cleared=ok(out,dict(type='set_cart',customer_id='c',items=[]));assert cleared['carts']['c']['subtotal']==0 and cleared['carts']['c']['items']==[]
 obs=rows(cli(s,[{'command':'act','value':action},{'command':'show'}]));assert obs[2]['carts']['c']['subtotal']==32
 assert cart_quantities(obs[2]['carts']['c']['items'])=={'p':2,'s':1}

def test_ru_003_checkout():
 action=dict(type='set_cart',customer_id='c',items=[{'product_id':'p','quantity':1},{'product_id':'s','quantity':1},{'product_id':'p','quantity':1}])
 chained=ok(ok(base(),action),checkout());assert chained['orders']['o']['subtotal']==32 and chained['orders']['o']['total']==25.5
 persisted=rows(cli(base(),[{'command':'act','value':action},{'command':'act','value':checkout()},{'command':'show'}]));assert persisted[-1]['orders']['o']['total']==25.5
 s=withcart();s['carts']['c']['subtotal']=999
 for mode in ['pickup','preorder','delivery']:
  out=ok(s,checkout(mode=mode,zone_id='near'));order=out['orders']['o'];assert order['subtotal']==32 and order['total']==25.5 and order['mode']==mode and order['status']=='pending' and order['paid'] is False
 for kwargs in [{'mode':'invalid'},{'mode':'delivery','zone_id':'far'},{'mode':'delivery','zone_id':'missing'},{'coupon_code':'OLD'},{'coupon_code':'absent'},{'redeem_points':501},{'redeem_points':True}]:denied(s,checkout(**kwargs))
 small=withcart();small['zones']['near']['minimum']=32.01;denied(small,checkout(mode='delivery',zone_id='near'))
 changed=withcart();changed['products']['p']['active']=False;denied(changed,checkout())
 existing=orderstate();denied(existing,checkout());denied(base(),checkout())
 tiny=withcart();tiny['carts']['c']['items']=[{'product_id':'s','quantity':1}];tiny['products']['s']['price']=2.675;assert ok(tiny,checkout(coupon_code=None,redeem_points=0))['orders']['o']['total']==2.68
 assert ok(tiny,checkout(coupon_code=None,redeem_points=500))['orders']['o']['total']==0
 obs=rows(cli(withcart(),[{'command':'act','value':checkout()},{'command':'show'}]));assert obs[2]['orders']['o']['total']==25.5

def test_ru_004_points_payments():
 out=ok(withcart(),checkout());assert out['customers']['c']['points']==500 and out['orders']['o']['total']==25.5
 s=orderstate();paid=ok(s,dict(type='mark_paid',order_id='o',payment_event_id='event'));assert paid['customers']['c']['points']==275 and paid['orders']['o']['paid'] is True and paid['orders']['o']['status']=='pending'
 replay=ok(paid,dict(type='mark_paid',order_id='o',payment_event_id='event'));same(paid,replay)
 denied(paid,dict(type='mark_paid',order_id='o',payment_event_id='new'))
 other=deepcopy(paid);other['orders']['p']={**deepcopy(s['orders']['o']),'redeemed_points':0};denied(other,dict(type='mark_paid',order_id='p',payment_event_id='event'))
 low=orderstate();low['customers']['c']['points']=100;denied(low,dict(type='mark_paid',order_id='o',payment_event_id='later'))
 denied(s,dict(type='mark_paid',order_id='missing',payment_event_id='event'));denied(s,dict(type='mark_paid',order_id='o',payment_event_id=''))
 obs=rows(cli(s,[{'command':'act','value':dict(type='mark_paid',order_id='o',payment_event_id='persist')},{'command':'act','value':dict(type='mark_paid',order_id='o',payment_event_id='persist')},{'command':'show'}]));assert obs[3]['customers']['c']['points']==275 and obs[3]['orders']['o']['paid'] is True

def test_ru_005_reservations_status():
 s=base();reserve=dict(type='reserve',reservation_id='r',slot='evening-A',party_size=3);s=ok(s,reserve);assert s['reservations']['r']['slot']=='evening-A' and s['reservations']['r']['party_size']==3
 for action in [{**reserve,'reservation_id':'q'},{**reserve,'slot':'evening-B'},{**reserve,'reservation_id':'q','slot':'B','party_size':True},{**reserve,'reservation_id':'q','slot':'B','party_size':0}]:denied(s,action)
 s=orderstate();denied(s,dict(type='advance_order',actor_id='guest',order_id='o',status='accepted'));denied(s,dict(type='advance_order',actor_id='admin',order_id='o',status='ready'))
 for status in ['accepted','preparing','ready','completed']:
  s=ok(s,dict(type='advance_order',actor_id='admin',order_id='o',status=status));assert s['orders']['o']['status']==status
 denied(s,dict(type='advance_order',actor_id='admin',order_id='o',status='pending'))
 obs=rows(cli(base(),[{'command':'act','value':reserve},{'command':'act','value':{**reserve,'reservation_id':'q'}},{'command':'show'}]));assert obs[2]['error']['code'] and set(obs[3]['reservations'])=={'r'}
