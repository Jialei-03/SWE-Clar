from copy import deepcopy
from html.parser import HTMLParser
from candidate_proxy import call,cli

def records():
 a={'id':'b','business_name':'Beta <Transit>','country_code':'US','state_name':'Northland','state_code':'NL','main_city':'River City','other_cities':['Oak Town','Oak Town'],'services':['Piano','Storage','Piano'],'sponsored':False}
 b={**a,'id':'a','business_name':'Alpha Transport','other_cities':[],'services':['Piano'],'sponsored':True}
 c={**b,'id':'c','business_name':'Cedar Haul','state_name':'Southland','state_code':'SL','other_cities':[],'sponsored':False}
 return [a,b,c]
def req(rows=None,changed=None,**extra):return {'records':records() if rows is None else rows,'changed_ids':[] if changed is None else changed,**extra}
def pages(out):return {p['route']:p for p in out['pages']}
def rejected(request):assert call(request).get('rejected') is True

def test_ru_001_validation_determinism_pagination():
 request=req();out=call(request);assert all(k in out for k in ['pages','suggestions','cache_queue']) and out==call(request)
 assert out==call(req(list(reversed(records()))))
 assert call(req([]))['pages']==[]
 for field,value in [('records',{}),('changed_ids',['missing']),('query',2),('immediate_ids','a')]:rejected({**request,field:value})
 for field,value in [('id',''),('business_name',''),('services',['']),('other_cities','Town'),('sponsored',1)]:
  rows=records();rows[0][field]=value;rejected(req(rows))
 rows=records();rows[0]['id']='a';rejected(req(rows))
 one=cli(request,0,2);two=cli(request,2,100);assert one['returncode']==two['returncode']==0
 assert one['output']['total_pages']==len(out['pages']) and len(one['output']['pages'])==2
 assert [x['route'] for x in one['output']['pages']+two['output']['pages']]==[x['route'] for x in out['pages']]
 assert cli(request,-1,2)['output'].get('error') and cli(request,0,0)['output'].get('error')

class Text(HTMLParser):
 def __init__(self):super().__init__();self.values=[];self.tags=[]
 def handle_data(self,data):self.values.append(data)
 def handle_starttag(self,tag,attrs):self.tags.append(tag)

def label_controls():
 variants=records()[:2]
 variants[0].update(main_city=' River City ',other_cities=['RIVER CITY','Ríver City'],services=['Piano',' PIANO ','Píano'])
 variants[1].update(main_city='RIVER CITY',other_cities=['River City'],services=['PIANO','Piano'])
 expected_labels={'/northland-piano-movers':'Northland PIANO Movers','/river-city-nl-movers':'RIVER CITY NL Movers','/river-city-nl-piano-movers':'RIVER CITY NL PIANO Movers'}
 for rows in [variants,list(reversed(variants)),[{**r,'services':list(reversed(r['services'])),'other_cities':list(reversed(r['other_cities']))} for r in variants]]:
  by_variant=pages(call(req(rows,query='river city')))
  for route,label in expected_labels.items():assert by_variant[route]['label']==label and by_variant[route]['business_ids']==['a','b']

def test_ru_002_membership_and_rendered_content():
 label_controls()
 out=call(req());by=pages(out)
 assert {p['kind'] for p in out['pages']}=={'state','state_service','city','city_service','business'}
 assert by['/northland-movers']['business_ids']==['a','b']
 assert by['/oak-town-nl-storage-movers']['business_ids']==['b']
 assert by['/river-city-nl-piano-movers']['business_ids']==['a','b']
 assert by['/river-city-sl-piano-movers']['business_ids']==['c']
 assert by['/northland-piano-movers']['label']=='Northland Piano Movers'
 for p in out['pages']:assert len(p['business_ids'])==len(set(p['business_ids']))
 rendered=cli(req(),0,100)['output']
 for page in rendered['pages']:
  parser=Text();parser.feed(page['html']);text=''.join(parser.values);assert page['label'] in text and 'transit' not in parser.tags
  names=[next(r['business_name'] for r in records() if r['id']==uid) for uid in page['business_ids']]
  assert all(name in text for name in names)
  assert [text.rfind(name) for name in names]==sorted(text.rfind(name) for name in names)

def test_ru_003_routes_and_collision_rejection():
 rows=records();rows[0].update(business_name='Café & Co',main_city='  New--Tówn ',other_cities=[],services=['Heavy / Lift']);out=call(req(rows));by=pages(out)
 assert '/business/cafe-co-b' in by and '/new-town-nl-heavy-lift-movers' in by
 assert '/river-city-nl-piano-movers' in by and '/river-city-sl-piano-movers' in by
 assert list(by)==sorted(by) and len(by)==len(out['pages']) and all('--' not in r and r==r.lower() for r in by)
 rows=records();rows[0]['services']=['!!!'];rejected(req(rows))
 rows=records();rows[2].update(state_name='Northland',state_code='NL',country_code='CA');rejected(req(rows))
 rows=records();rows.append({**rows[0],'id':'b!'});rejected(req(rows))

def test_ru_004_ranked_search_and_cap():
 exact=call(req(query=' ALPHA--Transport '))['suggestions'];assert exact[0]['kind']=='business' and exact[0]['score']==300
 prefix=call(req(query='River City NL Piano'))['suggestions'];assert prefix[0]['score']==200 and prefix[0]['target']=='/river-city-nl-piano-movers'
 sub=call(req(query='movers'))['suggestions'];assert len(sub)==10 and all(s['score']==100 for s in sub)
 assert [( -s['score'],s['target']) for s in sub]==sorted((-s['score'],s['target']) for s in sub)
 assert len({s['target'] for s in sub})==len(sub)
 for query in ['', '   ', '!!!',None]:assert call(req(query=query))['suggestions']==[]
 out=cli(req(query='movers'),0,1)['output'];assert len(out['suggestions'])==10

def test_ru_005_affected_routes_only():
 out=call(req(changed=['b','b']));expected={p['route'] for p in out['pages'] if 'b' in p['business_ids']};queue=out['cache_queue']
 assert {r['route'] for r in queue}==expected and len(queue)==len(expected)
 assert all(r['mode']=='nightly' for r in queue) and call(req())['cache_queue']==[]
 assert all('southland' not in r['route'] for r in queue)
 assert cli(req(changed=['b']),0,1)['output']['cache_queue']==queue

def test_ru_006_immediate_priority_independent_membership():
 out=call(req(changed=['b'],immediate_ids=['a','a']));queue={r['route']:r['mode'] for r in out['cache_queue']}
 assert list(queue)==sorted(queue)
 for page in out['pages']:
  expected='immediate' if 'a' in page['business_ids'] else 'nightly' if 'b' in page['business_ids'] else None
  assert queue.get(page['route'])==expected
 urgent=call(req(immediate_ids=['c']))
 assert {r['route'] for r in urgent['cache_queue']}=={p['route'] for p in urgent['pages'] if 'c' in p['business_ids']}
 assert all(r['mode']=='immediate' for r in urgent['cache_queue'])
