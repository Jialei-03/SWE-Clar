from copy import deepcopy
import math
from candidate_proxy import call,cli

COLLECTIONS=['clients','taskers','invitations','orders','invoices','payments','categories']
def base():return {'clients':{'c':{'completed_orders':{'t':2}},'n':{'completed_orders':{'x':5}}},'taskers':{'t':{'recurring_discount':.15},'x':{'recurring_discount':.3}},'invitations':{},'orders':{},'invoices':{},'payments':[],'categories':{}}
def same(a,b):
 for key in COLLECTIONS:assert a.get(key,[] if key=='payments' else {})==b.get(key,[] if key=='payments' else {}),key
def created_result(s,a,out):
 spec={'invite_monthly':('invitation_id','invitations'),'accept_monthly':('order_id','orders'),'issue_invoice':('invoice_id','invoices')}.get(a.get('type'))
 if spec:
  field,collection=spec;ident=out['result'][field];assert isinstance(ident,str) and ident
  assert ident in out[collection]
  if field in a:assert ident==a[field]
  else:assert set(out[collection])-set(s.get(collection,{}))=={ident}
 return out
def ok(s,a):
 out=call(s,a);assert 'error' not in out,out;return created_result(s,a,out)
def denied(s,a):
 out=call(s,a);assert out.get('error',{}).get('code'),out;same(out,s);return out
def invite(s=None,i='i',c='c',t='t',months=2):return ok(base() if s is None else s,dict(type='invite_monthly',invitation_id=i,client_id=c,tasker_id=t,monthly_amount=125,months=months))
def accepted():return ok(invite(),dict(type='accept_monthly',invitation_id='i',client_id='c',order_id='o',first_due=20))
def issue(s,now=20):return ok(s,dict(type='issue_invoice',order_id='o',now=now))
def check_cli(rows):
 assert all(r['returncode']==0 and isinstance(r['output'],dict) for r in rows),rows
 return [r['output'] for r in rows]

def test_ru_001_entry():
 s=base();out=ok(s,dict(type='quote',client_id='c',tasker_id='t',amount=0));assert isinstance(out,dict)
 denied(s,{'type':'unknown'});denied(s,{})
 rows=check_cli(cli(s,[{'command':'act','value':{'type':'quote','client_id':'c','tasker_id':'t','amount':0}},{'command':'show'},{'command':'act','value':[]},{'command':'show'}]));assert 'error' not in rows[1];same(rows[1],rows[2]);assert rows[2].get('result',{}).get('amount')==0;assert rows[3]['error']['code'];assert rows[2]==rows[4]

def test_ru_002_discount():
 s=base()
 for client,tasker,amount,rate,eligible in [('c','t',80,.15,True),('n','t',80,0,False),('c','x',10,0,False),('n','x',10,.3,True)]:
  r=ok(s,dict(type='quote',client_id=client,tasker_id=tasker,amount=amount,subscription=True,recurring=True))['result'];assert math.isclose(r['amount'],amount*(1-rate));assert r['discount_rate']==rate and r['recurring'] is eligible and r['subscription'] is False
 s['orders']['monthly']={'client_id':'n','tasker_id':'t','status':'active'};assert ok(s,dict(type='quote',client_id='n',tasker_id='t',amount=50))['result']['amount']==50
 for amount in [-1,True,'20',float('inf')]:denied(s,dict(type='quote',client_id='c',tasker_id='t',amount=amount))
 for rate in [-.1,1.1,True]:
  bad=deepcopy(s);bad['taskers']['t']['recurring_discount']=rate;denied(bad,dict(type='quote',client_id='c',tasker_id='t',amount=10))
 denied(s,dict(type='quote',client_id='missing',tasker_id='t',amount=10))

def test_ru_003_agreements():
 s=invite();assert s['invitations']['i']['monthly_amount']==125
 denied(s,dict(type='invite_monthly',invitation_id='i',client_id='c',tasker_id='t',monthly_amount=1,months=1))
 for amount,months in [(0,1),(-1,1),(10,0),(10,1.5),(10,True)]:denied(base(),dict(type='invite_monthly',invitation_id='z',client_id='c',tasker_id='t',monthly_amount=amount,months=months))
 denied(s,dict(type='accept_monthly',invitation_id='i',client_id='n',order_id='o',first_due=20))
 s=accepted();r=s['orders']['o'];assert all(r[k]==v for k,v in {'client_id':'c','tasker_id':'t','monthly_amount':125,'months':2,'first_due':20,'status':'active'}.items())
 again=call(s,dict(type='accept_monthly',invitation_id='i',client_id='c',order_id='o',first_due=20));same(s,again)
 denied(s,dict(type='accept_monthly',invitation_id='i',client_id='c',order_id='z',first_due=20))
 other=invite(s,'j');denied(other,dict(type='accept_monthly',invitation_id='j',client_id='c',order_id='z',first_due=20))
 other=invite(s,'k','n');denied(other,dict(type='accept_monthly',invitation_id='k',client_id='n',order_id='o',first_due=20))
 out=ok(other,dict(type='accept_monthly',invitation_id='k',client_id='n',order_id='p',first_due=0));assert len(out['orders'])==2
 actions=[dict(type='invite_monthly',invitation_id='cli-i',client_id='c',tasker_id='t',monthly_amount=125,months=2),dict(type='accept_monthly',invitation_id='cli-i',client_id='c',order_id='cli-o',first_due=20),dict(type='issue_invoice',order_id='cli-o',now=20)]
 observations=check_cli(cli(base(),[op for a in actions for op in [{'command':'act','value':a},{'command':'show'}]]))
 prior=observations[0]
 for i,a in enumerate(actions):
  actual=observations[1+2*i];created_result(prior,a,actual);same(actual,observations[2+2*i]);prior=observations[2+2*i]

def test_ru_004_lifecycle():
 s=accepted();denied(s,dict(type='issue_invoice',order_id='o',now=19));s=issue(s);r=s['invoices']['o:1'];assert all(r[k]==v for k,v in {'order_id':'o','sequence':1,'amount':125,'status':'due'}.items())
 denied(s,dict(type='issue_invoice',order_id='o',now=20+30*86400-1));s=issue(s,20+30*86400);assert s['invoices']['o:2']['sequence']==2
 denied(s,dict(type='issue_invoice',order_id='o',now=10**9))
 paid=ok(s,dict(type='pay_invoice',invoice_id='o:1',event_id='event'));replay=ok(paid,dict(type='pay_invoice',invoice_id='o:1',event_id='event'));same(paid,replay);assert replay['payments']==['event'] and replay['invoices']['o:1']['status']=='paid'
 denied(paid,dict(type='pay_invoice',invoice_id='o:2',event_id='event'));denied(paid,dict(type='pay_invoice',invoice_id='o:1',event_id='different'));denied(paid,dict(type='pay_invoice',invoice_id='missing',event_id='new'))
 late=issue(accepted(),10**9);assert set(late['invoices'])=={'o:1'}
 operations=[{'command':'act','value':dict(type='pay_invoice',invoice_id='o:1',event_id='cli-event')},{'command':'show'},{'command':'act','value':dict(type='pay_invoice',invoice_id='o:1',event_id='cli-event')},{'command':'show'},{'command':'act','value':dict(type='pay_invoice',invoice_id='o:2',event_id='cli-event')},{'command':'show'}]
 rows=check_cli(cli(s,operations));assert rows[2]['payments']==['cli-event'] and rows[2]['invoices']['o:1']['status']=='paid';same(rows[2],rows[4]);assert rows[5]['error']['code'];assert rows[4]==rows[6]

def test_ru_005_categories_admin():
 s=base()
 for i,parent,depth in [('a',None,1),('b','a',2),('c','b',3)]:s=ok(s,dict(type='add_category',category_id=i,parent_id=parent));assert s['categories'][i]['depth']==depth
 for i,parent in [('d','c'),('a',None),('e','missing'),('self','self')]:denied(s,dict(type='add_category',category_id=i,parent_id=parent))
 corrupted=deepcopy(s);corrupted['categories']['b']['parent_id']='c';denied(corrupted,dict(type='add_category',category_id='q',parent_id='b'))
 for role in ['user','moderator','agent',None]:denied(s,dict(type='admin_tabs',role=role))
 tabs=ok(s,dict(type='admin_tabs',role='admin'))['result']['tabs'];names={x['name'] for x in tabs};assert {'Moderator','Agents'}<=names;assert all(x['route'].startswith('/admin/') for x in tabs if x['name'] in {'Moderator','Agents'})
