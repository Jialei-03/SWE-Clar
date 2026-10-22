from candidate_proxy import browser
from urllib.parse import urlsplit

def data():return {'summary':{'active':7,'available':3},'drivers':[{'id':'d1','name':'Synthetic Driver Alpha'},{'id':'d2','name':'Synthetic Driver Beta'}],'vehicles':[{'id':'v1','name':'Example Van'},{'id':'v2','name':'Example Truck'}]}
def separated(a,b,axis):
 size='width' if axis=='x' else 'height'
 return a[axis]+a[size]<=b[axis]+1 or b[axis]+b[size]<=a[axis]+1
def panel_content(row,value,target):
 assert row['panel_visible']
 text=row['panel'];names=[x['name'] for x in value[target]]
 assert all(n in text for n in names) and [text.index(n) for n in names]==sorted(text.index(n) for n in names)
 other='vehicles' if target=='drivers' else 'drivers'
 assert all(x['name'] not in text for x in value[other])
def has_content(row,value):
 for key,v in value['summary'].items():assert key in row['summary'] and str(v) in row['summary']
 for field in ['drivers','vehicles']:
  text=row[field];names=[r['name'] for r in value[field]];assert all(name in text for name in names);assert [text.index(name) for name in names]==sorted(text.index(name) for name in names)
 assert row['data']==value and not row['page_errors']

def test_ru_001_actual_render_and_data_immutability():
 value=data();value['summary']={'total':13,'available':4};row=browser(value)[0];has_content(row,value)

def test_ru_002_responsive_geometry_at_boundaries():
 value=data();value['drivers'][0]['name']='LongDriverName'*25
 rows=browser(value,[{'op':'resize','width':w} for w in [320,599,600,1023,1024,1280]])
 for row in rows:
  has_content(row,value);width=row['viewport']['width'];a=row['driver_rect'];b=row['vehicle_rect'];assert row['width']<=width+1 and a and b
  assert min(a['x'],b['x'])>=-1 and max(a['x']+a['width'],b['x']+b['width'])<=width+1
  assert separated(a,b,'y' if width<600 else 'x')

def test_ru_003_missing_data_is_accessible_not_fabricated():
 for keys in [['summary'],['drivers'],['vehicles'],['summary','vehicles']]:
  value=data()
  for key in keys:value.pop(key)
  row=browser(value)[0];assert 'missing_data' in row['error'] and all(k in row['error'] for k in keys) and row['error_accessible']
  assert not row['summary'] and not row['drivers'] and not row['vehicles'] and row['data']==value and not row['page_errors']

def test_ru_004_local_panels_controls_and_dispatch():
 # Exercise both real controls through reachable user interactions. A valid
 # fixed sidebar may cover background buttons until its Close control is used.
 # Direct switching of an already-open panel is independently tested through
 # the explicitly specified dispatch interface in both directions.
 value=data();rows=browser(value,[{'op':'click','selector':'#view-drivers'},{'op':'click','selector':'#close-sidebar'},{'op':'click','selector':'#view-vehicles'},{'op':'click','selector':'#close-sidebar'},{'op':'dispatch','action':{'type':'view_all','target':'drivers'}},{'op':'dispatch','action':{'type':'view_all','target':'vehicles'}},{'op':'dispatch','action':{'type':'view_all','target':'drivers'}},{'op':'dispatch','action':{'type':'close_sidebar'}}])
 for i,target in [(0,'drivers'),(2,'vehicles'),(4,'drivers'),(5,'vehicles'),(6,'drivers')]:panel_content(rows[i],value,target)
 for i in [1,3,7]:assert rows[i]['panel_visible'] is False
 assert all(r['data']==value for r in rows)

def test_ru_005_safe_text_offline_and_unknown_action_no_effect():
 value=data();value['drivers'][0]['name']='<img src="bad" onerror="window.__EXECUTED=true">';value['summary']['<img src=x>']='literal'
 rows=browser(value,[{'op':'observe'},{'op':'dispatch','action':{'type':'unknown'}},{'op':'click','selector':'#view-drivers'},{'op':'dispatch','action':{'type':'view_all','target':'missing'}},{'op':'dispatch','action':None}])
 for i in [1,3,4]:assert rows[i]['dispatch_result']['error']['code']=='unknown_action'
 assert rows[0]['panel_visible']==rows[1]['panel_visible'] is False and rows[2]['panel']==rows[3]['panel']==rows[4]['panel']
 for row in rows:
  has_content(row,value);assert row['injected_elements']==0 and not row['executed'];assert all(urlsplit(u).hostname in ('127.0.0.1','localhost') for u in row['requests'])
