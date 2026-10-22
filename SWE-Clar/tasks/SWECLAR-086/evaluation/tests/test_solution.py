import json
from candidate_proxy import call,cli

def good(**updates):return {'businessStatus':'OPERATIONAL','rating':4,'userRatingCount':100,'types':['cafe'],'place_id':'primary',**updates}
def activity(name='A'):return {'business_name':name,'description':'Visit '+name,'day':1,'extra':{'keep':True}}
def request(operation,**data):return {'operation':operation,'location':'Synthetic Town',**data}
def payloads(text):
 rows=[]
 for event in text.split('\n\n'):
  if not event:continue
  assert event.startswith('data:');rows.append(json.loads(event[5:].strip()))
 return rows

def test_ru_001_incremental_nested_objects_and_six_line_layout():
 a={'name':'brace } and escaped " quote','nested':[{'value':'\\'}],'number':2};b={'other':True};wire=json.dumps(a)+json.dumps(b)
 for chunks in [[wire],[c for c in wire],[wire[:11],wire[11:]+ '{"unfinished":']]:
  out=call(request('parse',chunks=chunks));assert [r['value'] for r in out['value']]==[a,b]
 six='''{
"business_name":"A",
"description":"Visit",
"day":1,
"metadata":{}
}'''
 out=call(request('parse',chunks=[six,json.dumps(b)],limit=1));assert out['value'][0]['value']['business_name']=='A' and out['consumed']==1
 assert call(request('parse',chunks=['',' \n']))['value']==[]
 for chunks in [['[]'],['{bad}'],[1]]:assert call(request('parse',chunks=chunks)).get('rejected')

def test_ru_002_primary_merge_and_no_replacement():
 a=activity();place=good(description='Provider description',opaque={'nested':[1,2]});out=call(request('resolve',activity=a,primary={'A':place},replacement={'Visit A':good(place_id='unused')}))
 expected={**a,**place};assert all(out['value'][k]==v for k,v in expected.items())
 assert out['calls']==[{'kind':'primary','key':'A','location':'Synthetic Town'}]

def test_ru_003_acceptance_thresholds_and_all_exemptions():
 for place,expected in [(good(),True),(good(rating=3,userRatingCount=50),True),(good(rating=2.99),False),(good(userRatingCount=49),False),(good(rating=True),False),(good(userRatingCount=True),False),(None,False),(good(types='park'),False)]:assert call(request('valid',place=place))['value'] is expected
 for kind in ['neighborhood','natural_feature','route','tourist_attraction','point_of_interest','park']:
  exempt={'businessStatus':'OPERATIONAL','types':['other',kind]};assert call(request('valid',place=exempt))['value'] is True
  for status in ['CLOSED_TEMPORARILY','CLOSED_PERMANENTLY']:assert call(request('valid',place={**exempt,'businessStatus':status}))['value'] is False
 for place in [good(rating=float('inf')),good(userRatingCount=50.0)]:assert call(request('valid',place=place))['value'] is False

def test_ru_004_replacement_revalidation_and_merge():
 a=activity();replacement=good(place_id='replacement',details={'provider':'local'});out=call(request('resolve',activity=a,primary={'A':good(rating=1)},replacement={'Visit A':replacement}));assert all(out['value'][k]==v for k,v in {**a,**replacement}.items())
 assert out['calls']==[{'kind':'primary','key':'A','location':'Synthetic Town'},{'kind':'replacement','key':'Visit A','location':'Synthetic Town'}]
 for place in [None,good(rating=1),good(businessStatus='CLOSED_PERMANENTLY',types=['park'])]:assert call(request('resolve',activity=a,primary={},replacement={'Visit A':place}))['value'] is None

def test_ru_005_real_open_pipe_delivery_and_order():
 a=activity('A');b=activity('B');bad=activity('bad');primary={'A':good(place_id='first'),'B':good(place_id='second')};chunks=[json.dumps(a),json.dumps(bad),json.dumps(b)]
 direct=call(request('stream',chunks=chunks,primary=primary,replacement={}));rows=direct['value'];assert rows[0]['consumed']==1 and [payloads(r['value'])[0]['place_id'] for r in rows]==['first','second']
 actual=cli({'places':{'primary':primary,'replacement':{}},'location':'Synthetic Town','first':chunks[0],'rest':chunks[1]+chunks[2]})
 assert actual['returncode']==0,actual['stderr'];early=payloads(actual['early']);assert len(early)==1 and early[0]['place_id']=='first'
 assert [p['place_id'] for p in payloads(actual['stdout'])]==['first','second']
