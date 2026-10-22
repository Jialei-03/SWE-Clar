from pathlib import Path
import os,json,subprocess,traceback,base64
import sys,math
from playwright.sync_api import sync_playwright
sys.path.insert(0,'/opt/sweclar');from wordpress_fixture import WordPress
sys.path.insert(0,'/public_tests');from browser_isolation import launch
class HarnessUnavailable(RuntimeError):pass
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','.')).resolve();TESTS=Path(__file__).resolve().parent
def browser(w):
 with sync_playwright() as p:
  browser=launch(p.chromium,headless=True)
  try:
   page=browser.new_page(viewport={'width':1000,'height':1000});page.set_default_timeout(7000)
   page.add_init_script("""(()=>{window.nativePaint=[];window.nativeEvents=[];window.nativeShifts=[];if(PerformanceObserver.supportedEntryTypes.includes('largest-contentful-paint'))new PerformanceObserver(l=>nativePaint.push(...l.getEntries().map(x=>x.startTime))).observe({type:'largest-contentful-paint',buffered:true});if(PerformanceObserver.supportedEntryTypes.includes('event'))new PerformanceObserver(l=>nativeEvents.push(...l.getEntries().map(x=>({duration:x.duration,id:x.interactionId})))).observe({type:'event',buffered:true,durationThreshold:16});if(PerformanceObserver.supportedEntryTypes.includes('layout-shift'))new PerformanceObserver(l=>nativeShifts.push(...l.getEntries().filter(x=>!x.hadRecentInput).map(x=>x.value))).observe({type:'layout-shift',buffered:true});document.addEventListener('pointerdown',()=>{const end=performance.now()+60;while(performance.now()<end){}},true)})()""")
   page.goto(w.url+'/?directory_page=members');page.wait_for_function('!!window.directoryReadiness');page.locator('#filter').fill('Alpha');page.get_by_role('button',name='Filter',exact=True).click();page.wait_for_function("document.querySelector('#filter-status').textContent==='1 matching members'")
   page.wait_for_timeout(700);page.evaluate("()=>{const space=document.createElement('div');space.style.height='80px';document.querySelector('main').prepend(space)}");page.wait_for_timeout(350)
   r=page.evaluate("""()=>({support:PerformanceObserver.supportedEntryTypes,cards:[...document.querySelectorAll('#members article:not([hidden])')].map(n=>n.dataset.member),assets:[...document.querySelectorAll('link[href*="synthetic-directory"],script[src*="synthetic-directory"]')].map(n=>({tag:n.tagName,url:n.href||n.src,defer:n.defer||false})),metrics:window.directoryMeasurements,paints:window.nativePaint,events:window.nativeEvents,shifts:window.nativeShifts,ready:window.directoryReadiness(window.directoryMeasurements),boundaries:window.directoryReadiness({LCP:2500,INP:200,CLS:.1}),slow:window.directoryReadiness({LCP:2501,INP:201,CLS:.11}),invalid:window.directoryReadiness({LCP:-1,INP:Infinity,CLS:null}),extra:window.directoryReadiness({LCP:NaN,INP:true})})""")
   r['layouts']=[]
   for width in [360,768,1024]:page.set_viewport_size({'width':width,'height':1000});r['layouts'].append(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
   page.goto(w.url+'/?directory_page=about');r['about_filter']=page.locator('script[src*="synthetic-directory/filter.js"]').count()
   Path('/private/results').mkdir(parents=True,exist_ok=True);open('/private/results/performance-observations.jsonl','a').write(json.dumps(r)+'\n');return r
  finally:browser.close()
def ru001(w):
 code,body,headers=w.get();assert code==200 and b'Member directory' in body
 assert w.get('/?directory_page=unknown')[0]==404
 w.option('directory_members',[{'id':'test','name':'<script>window.customerLeak=true</script>','group_code':1,'activity_count':0}]);body=w.get()[1];assert b'&lt;script&gt;' in body and b'<script>window.customerLeak' not in body
 assert w.php("echo json_encode(get_option('directory_members'));").find('customerLeak')>=0
def ru002(w):
 code,first,h=w.get();assert code==200 and h.get('X-Directory-Cache')=='MISS';count=int(w.php("echo get_option('directory_render_count');"));_,second,h=w.get();assert h.get('X-Directory-Cache')=='HIT' and first.split(b'</nav>',1)[-1].split(b'<details>',1)[0]==second.split(b'</nav>',1)[-1].split(b'<details>',1)[0] and int(w.php("echo get_option('directory_render_count');"))==count
 cookie=w.logged_cookie();_,private,h=w.get(cookie=cookie);assert h.get('X-Directory-Cache')=='BYPASS' and b'Signed in as Example Editor' in private
 _,public,h=w.get();assert b'Signed in as Example Editor' not in public and h.get('X-Directory-Cache')=='HIT'
 assert w.get('/?directory_page=members&preview=true')[2].get('X-Directory-Cache')=='BYPASS'
 w.option('directory_members',[{'id':'new','name':'Changed example member','group_code':4,'activity_count':2}]);_,changed,h=w.get();assert h.get('X-Directory-Cache')=='MISS' and b'Changed example member' in changed
 assert b'About this directory' in w.get('/?directory_page=about')[1] and b'Changed example member' not in w.get('/?directory_page=about')[1]
 w.option('directory_content_version',999);assert w.get()[2].get('X-Directory-Cache')=='MISS'
def ru003(w):
 r=browser(w);assets=r['assets'];assert r['cards']==['member-a'] and not any(r['layouts']);assert sum(x['url'].split('?')[0].endswith('/style.css') for x in assets)==1
 scripts=[i for i,x in enumerate(assets) if x['tag']=='SCRIPT'];styles=[i for i,x in enumerate(assets) if x['tag']=='LINK'];assert scripts and styles and max(styles)<min(scripts) and all(assets[i]['defer'] for i in scripts),r
 assert r['about_filter']==0
def ru004(w):
 source=[{'id':'a','name':'Example','group_code':0,'activity_count':0},{'id':'b','name':'Example','group_code':'03','activity_count':None},{'id':'c','name':'Example','group_code':9},{'id':'d','name':'Example','group_code':10,'activity_count':''},{'id':'e','name':'Example','group_code':0.0,'activity_count':0.0}];encoded=base64.b64encode(json.dumps(source).encode()).decode();r=json.loads(w.php('echo json_encode(array_map("directory_normalize_member",json_decode(base64_decode('+repr(encoded)+'),true)));'));assert [x['group_code'] for x in r]==['00','03','09','10','00'] and [x['activity_count'] for x in r]==[0,None,None,None,0]
 for key,value in [('group_code',True),('group_code',-1),('group_code','abc'),('activity_count',False),('activity_count',-1),('activity_count','abc')]:
  row=base64.b64encode(json.dumps({'id':'a','name':'Example',key:value}).encode()).decode();result=w.php('try {directory_normalize_member(json_decode(base64_decode('+repr(row)+'),true));echo "accepted";}catch(Throwable $e){echo "rejected";}');assert result=='rejected'
 with sync_playwright() as p:
  session=launch(p.chromium,headless=True)
  try:
   page=session.new_page();page.goto(w.url+'/?directory_page=members')
   assert_member_display(page.locator('.activity_count').all_inner_texts(),page.locator('.group_code').all_inner_texts())
  finally:session.close()
def assert_member_display(counts,groups):
 assert {'0','Unavailable'}<={' '.join(x.split()) for x in counts}
 assert '00' in {' '.join(x.split()) for x in groups}
def ru005(w):
 r=browser(w)
 for key,ready,failed,missing in [('boundaries',True,[],[]),('slow',False,['LCP','INP','CLS'],[]),('invalid',False,[],['LCP','INP','CLS']),('extra',False,[],['LCP','INP','CLS'])]:
  v=r[key];assert v['ready'] is ready and set(v['failed'])==set(failed) and set(v['missing'])==set(missing),v
 interactions=[x['duration'] for x in r['events'] if x['id']]
 if not {'largest-contentful-paint','event','layout-shift'}<=set(r['support']) or not r['paints'] or not interactions or not r['shifts']:raise HarnessUnavailable('Native observers did not produce the controlled workload evidence')
 m=r['metrics'];assert all(type(m.get(k)) in [int,float] and math.isfinite(m[k]) and m[k]>=0 for k in ['LCP','INP','CLS']),r
 assert abs(m['LCP']-max(r['paints']))<2 and abs(m['INP']-max(interactions))<20 and abs(m['CLS']-sum(r['shifts']))<1e-6,r
 expected={name for name,limit in {'LCP':2500,'INP':200,'CLS':.1}.items() if m[name]>limit};assert set(r['ready']['failed'])==expected and r['ready']['missing']==[] and r['ready']['ready']==(not expected)
 # Hardware-dependent values above limits are reported, never themselves a failure.
def main():
 if not (Path('/public_tests')/'browser_launcher.py').is_file():return {'harness_ok':False,'infrastructure_errors':['Missing browser helper'],'results':[]}
 w=None;rows=[]
 try:
  w=WordPress(ROOT)
  for i,test in enumerate([ru001,ru002,ru003,ru004,ru005],1):
   try:w.reset();test(w);row={'ru_id':f'RU-{i:03}','passed':True}
   except HarnessUnavailable as e:return {'harness_ok':False,'infrastructure_errors':[str(e)],'results':rows}
   except Exception as e:row={'ru_id':f'RU-{i:03}','passed':False,'detail':str(e) or type(e).__name__,'trace':traceback.format_exc()[-1800:]}
   rows.append(row)
 except AssertionError as e:return {'harness_ok':True,'results':[{'ru_id':f'RU-{i:03}','passed':False,'detail':str(e)} for i in range(1,6)]}
 except Exception as e:return {'harness_ok':False,'infrastructure_errors':[str(e) or type(e).__name__],'results':rows}
 finally:
  if w:
   Path('/private/results').mkdir(parents=True,exist_ok=True);(Path('/private/results')/'service-isolation.jsonl').write_text(json.dumps(w.server_proof)+'\n');(Path('/private/results')/'php-cli-isolation.jsonl').write_text(w.proof.read_text());w.close()
 return {'harness_ok':True,'results':rows}
if __name__=='__main__':print(json.dumps(main()))
