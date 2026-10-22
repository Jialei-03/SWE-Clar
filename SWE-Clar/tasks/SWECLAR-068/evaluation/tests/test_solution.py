import json,os,subprocess,sys
from copy import deepcopy
from playwright.sync_api import expect
from browser_support import App,ROOT,WHITE_PATH

def call(config,context):
 result=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(ROOT),'config':config,'context':context}),text=True,capture_output=True,timeout=10,cwd=ROOT,user=1000,group=1000,extra_groups=[],env={'PATH':WHITE_PATH,'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
 assert result.returncode==0,result.stderr[-300:];out=json.loads(result.stdout);assert out['config_after']==config and out['context_after']==context;assert isinstance(out['result'],dict);return out['result']
def visible(element):
 expect(element).to_be_visible();assert element.evaluate('(e)=>{for(let n=e;n;n=n.parentElement){let s=getComputedStyle(n);if(Number(s.opacity)===0||s.visibility==="hidden"||s.display==="none")return false}return true}')
def test_ru_001_entry_cli_and_inputs():
 c={'triggers':{'standard':True},'unrelated':{'nested':[1,2]}};x={'trigger_states':{'standard':True},'htf1':'bull','untouched':[{'x':1}]};before=deepcopy((c,x));one=call(c,x);two=call(c,x);assert (c,x)==before
 # Extra top-level or nested metadata is permitted; compare only contract fields.
 assert one['active_signals']==two['active_signals'];assert one['classification']==two['classification'];assert one['tf1_active']==two['tf1_active'];assert one['labels_visible']==two['labels_visible']
 for key in ['htf1','htf2','regression']:assert one['styles'][key]==two['styles'][key]
 for key in ['visible','size']:assert one['menu'][key]==two['menu'][key]
 p=subprocess.run([sys.executable,str(ROOT/'cli.py')],input=json.dumps({'config':c,'context':x}),text=True,capture_output=True,timeout=10,cwd=ROOT,user=1000,group=1000,extra_groups=[],env={'PATH':WHITE_PATH,'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'});assert p.returncode==0;assert json.loads(p.stdout)['active_signals']==one['active_signals']

def test_ru_002_independent_controls():
 states={'z':True,'a':True,'idle':False,'missing':True}
 for enabled in [{'z':True,'a':False,'idle':True},{'z':False,'a':True,'idle':True},{'a':True,'z':True},{}, {'missing':True}]:
  assert call({'triggers':enabled},{'trigger_states':states,'htf1':'bear'})['active_signals']==[name for name,value in states.items() if value and enabled.get(name) is True]
 assert call({'triggers':{'z':True,'a':True}},{'trigger_states':{'a':True,'z':True},'htf1':'bull'})['active_signals']==['a','z']

def test_ru_003_timeframe_selection():
 for first in ['bull','bear']:
  for second in ['bull','bear']:
   x={'htf1':first,'htf2':second,'trigger_states':{}}
   for selected in [False,True]:
    r=call({'tf2_enabled':selected},x);assert r['tf1_active'] is True;assert r['classification']==(('grade_a' if first==second else 'grade_b') if selected else first)
  assert call({}, {'htf1':first,'htf2':'bear'})['classification']==first
  assert call({'tf2_enabled':True},{'htf1':first,'htf2':None})['classification']==first
  assert call({'tf2_enabled':True},{'htf1':None,'htf2':first})['classification']==first

def test_ru_004_exact_blackout_toggle():
 for enabled in [False,True]:
  for when in ['09:30','09:31','09:30:00','x']:
   c={'triggers':{'x':True},'blackout_times':['09:30','x'],'blackout_enabled':enabled};x={'trigger_states':{'x':True},'htf1':'bull','time':when}
   assert call(c,x)['active_signals']==([] if enabled and when in c['blackout_times'] else ['x'])
 assert call({'triggers':{'x':True},'blackout_times':['09:30']},{'trigger_states':{'x':True},'htf1':'bull','time':'09:30'})['active_signals']==['x']

def test_ru_005_actual_presentation():
 c={'triggers':{'signal':True,'<literal>':True},'tf2_enabled':True,'menu_visible':True};x={'trigger_states':{'signal':True,'<literal>':True},'htf1':'bull','htf2':'bear','viewport_width':390}
 r=call(c,x);assert r['labels_visible'] is True;assert r['styles']['htf1']=='green' and r['styles']['htf2']=='red' and r['styles']['regression']=='#ff00e7';assert r['menu']['visible'] is True and r['menu']['size']=='mobile'
 assert call({**c,'menu_visible':False},x)['menu']['visible'] is False
 with App() as app:
  for width in [390,1280]:
   with app.page(width) as page:
    page.locator('#config').fill(json.dumps(c));page.locator('#context').fill(json.dumps(x))
    def evaluate():
     with page.expect_response(lambda response:response.url.endswith('/evaluate')) as response:page.get_by_role('button',name='Evaluate',exact=True).click()
     assert 200<=response.value.status<300
    evaluate();expect(page.locator('#labels text')).to_have_count(2);assert page.locator('#labels text').all_text_contents()==['signal','<literal>'];expect(page.locator('#labels literal')).to_have_count(0)
    for label in page.locator('#labels text').all():visible(label)
    for name,color in [('htf1','rgb(0, 128, 0)'),('htf2','rgb(255, 0, 0)'),('regression','rgb(255, 0, 231)')]:
     line=page.locator('#'+name);visible(line);assert line.evaluate('(e)=>getComputedStyle(e).stroke')==color;box=line.bounding_box();assert box and box['width']>100 and box['height']>5
    expect(page.locator('#menu')).to_be_visible();assert 'grade_b' in page.locator('#menu').inner_text();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.get_by_label('Show information menu',exact=True).uncheck();evaluate();expect(page.locator('#menu')).to_be_hidden()
    page.locator('#config').fill(json.dumps({**c,'blackout_enabled':True,'blackout_times':['09:30']}));page.locator('#context').fill(json.dumps({**x,'time':'09:30'}));evaluate();expect(page.locator('#labels text')).to_have_count(0)
