from playwright.sync_api import expect
from browser_support import App

def fixture():return {'metrics':{'patients':17,'liabilities':0,'completed':9,'chart_series':[0,2,7,4]},'onboarding_steps':['Choose a section','Inspect the supplied totals','Finish this guide']}
def action(page,value):
 result=page.evaluate('(action)=>{const before=structuredClone(action);const result=window.dashboard.dispatch(action);return {result,before,after:action}}',value);assert result['before']==result['after'];return result['result']
def metric_projection(page):
 return page.evaluate('''()=>({metrics:window.dashboard.snapshot().metrics,cards:[...document.querySelectorAll('[data-metric]')].map(n=>({key:n.dataset.metric,text:n.innerText})),labels:[...document.querySelectorAll('.chart-values li')].map(n=>n.innerText),marks:[...document.querySelectorAll('.chart svg rect')].map(n=>({value:n.dataset.value,height:n.getBoundingClientRect().height,width:n.getBoundingClientRect().width}))})''')
def test_ru_001_shell_and_input_copy():
 with App() as app,app.page(fixture()) as page:
  expect(page.get_by_role('heading',name='Patient dashboard',exact=True)).to_be_visible();expect(page.locator('.metric')).to_have_count(3)
  assert page.locator('[data-metric="patients"] .metric-value').inner_text()=='17';expect(page.locator('.chart svg')).to_be_visible()
  assert page.evaluate('()=>{let s=window.dashboard.snapshot();s.metrics.patients=999;return window.dashboard.snapshot().metrics.patients}')==17

def test_ru_002_responsive_geometry():
 with App() as app:
  for width in [320,599,600,1023,1024,1440]:
   with app.page(fixture(),width) as page:
    boxes=page.locator('.metric').evaluate_all('(nodes)=>nodes.map(n=>{let b=n.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height}})');assert len(boxes)==3;a,b,c=boxes
    if width<600:assert b['y']>=a['y']+a['h']-1 and c['y']>=b['y']+b['h']-1 and abs(a['x']-b['x'])<1
    elif width<1024:assert abs(a['y']-b['y'])<1 and b['x']>=a['x']+a['w']-1 and c['y']>=a['y']+a['h']-1
    else:assert abs(a['y']-b['y'])<1 and abs(b['y']-c['y'])<1 and b['x']>=a['x']+a['w']-1 and c['x']>=b['x']+b['w']-1
    assert all(x['x']>=-1 and x['w']>0 and x['x']+x['w']<=width+1 for x in boxes)
    assert page.evaluate('Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)<=innerWidth+1')
    box=page.get_by_role('button',name='Groups',exact=True).bounding_box();assert box and box['x']>=0 and box['x']+box['width']<=width+1

def test_ru_003_numeric_projection_and_rejection():
 with App() as app,app.page(fixture(),800) as page:
  metrics={'patients':0,'liabilities':125.75,'completed':3,'chart_series':[0,1,5]};action(page,{'type':'set_metrics','metrics':metrics})
  for key in ['patients','liabilities','completed']:assert page.locator('[data-metric="'+key+'"] .metric-value').inner_text()==str(metrics[key])
  assert page.locator('.chart-values li').all_text_contents()==['0','1','5']
  bars=page.locator('.chart svg rect').evaluate_all('(nodes)=>nodes.map(n=>({value:Number(n.dataset.value),height:n.getBoundingClientRect().height}))');assert [b['value'] for b in bars]==[0,1,5];assert bars[2]['height']>bars[1]['height']>bars[0]['height']
  for bad in [{'patients':'many'},{'patients':True},{'chart_series':[1,'bad']}]:
   before=metric_projection(page)
   assert action(page,{'type':'set_metrics','metrics':bad})['error']['code']=='invalid_metrics';assert page.locator('[data-metric="liabilities"] .metric-value').inner_text()=='125.75'
   assert metric_projection(page)==before
  for value in ['NaN','Infinity','-Infinity']:
   before=metric_projection(page)
   assert page.evaluate('()=>window.dashboard.dispatch({type:"set_metrics",metrics:{patients:'+value+'}})')['error']['code']=='invalid_metrics'
   assert metric_projection(page)==before
  assert page.locator('[data-metric="liabilities"] .metric-value').inner_text()=='125.75'

def test_ru_004_navigation_and_unknown_section():
 with App() as app:
  for width in [375,1280]:
   with app.page(fixture(),width) as page:
    for section in ['charts','scales','predictions','groups','patients']:
     button=page.get_by_role('button',name=section.title(),exact=True);button.click();expect(page.locator('#section-title')).to_have_text(section.title());assert button.get_attribute('aria-current')=='page';assert page.evaluate('window.dashboard.snapshot().active_section')==section
    before=page.locator('#section-title').inner_text();assert action(page,{'type':'navigate','section':'unknown'})['error']['code']=='unknown_section';assert page.locator('#section-title').inner_text()==before

def flow_fields(actual,steps,index,complete):
 assert actual['steps']==steps and actual['index']==index and actual['complete'] is complete

def test_ru_005_ordered_onboarding():
 with App() as app,app.page(fixture(),375) as page:
  steps=fixture()['onboarding_steps'];page.get_by_role('button',name='Start guide',exact=True).click()
  for i in range(3):
   expect(page.locator('#guide-content')).to_have_text(steps[i]);assert str(i) in page.locator('#guide-progress').inner_text() and '3' in page.locator('#guide-progress').inner_text();flow_fields(page.evaluate('window.dashboard.snapshot().onboarding'),steps,i,False);page.get_by_role('button',name='Next step',exact=True).click()
  expect(page.get_by_role('heading',name='Guide complete',exact=True)).to_be_visible();expect(page.get_by_role('button',name='Next step',exact=True)).to_have_count(0)
  for _ in range(2):flow_fields(action(page,{'type':'advance_onboarding'}),steps,3,True)
  flow_fields(page.evaluate('window.dashboard.snapshot().onboarding'),steps,3,True)
  for bad in [[],[''],['valid',None]]:
   result=action(page,{'type':'start_onboarding','steps':bad});assert isinstance(result['error']['code'],str) and result['error']['code'];flow_fields(page.evaluate('window.dashboard.snapshot().onboarding'),steps,3,True)
  literal=['A <literal> guide'];result=action(page,{'type':'start_onboarding','steps':literal});flow_fields(result,literal,0,False);expect(page.locator('#guide-content')).to_have_text(literal[0]);expect(page.locator('#guide-content literal')).to_have_count(0)
