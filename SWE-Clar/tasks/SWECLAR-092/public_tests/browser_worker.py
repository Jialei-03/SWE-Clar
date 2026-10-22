"""Ordinary-user static page server and browser observation worker."""
import json,sys,threading,functools,base64
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright
r=json.load(sys.stdin)
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=r['project']));threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page(viewport=r.get('viewport',{'width':1280,'height':900}));errors=[];requests=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda q:requests.append(q.url))
  if 'data' in r:page.add_init_script('window.FLEET_DATA='+json.dumps(r['data'])+';window.__EXECUTED=false;')
  page.goto('http://127.0.0.1:'+str(server.server_port)+'/index.html');page.wait_for_timeout(100)
  def observe():
   def rect(selector):return page.locator(selector).bounding_box()
   return {'data':page.evaluate('window.FLEET_DATA'),'summary':page.locator('#summary').inner_text(),'drivers':page.locator('#drivers').inner_text(),'vehicles':page.locator('#vehicles').inner_text(),'driver_rect':rect('#drivers-section'),'vehicle_rect':rect('#vehicles-section'),'viewport':page.viewport_size,'width':page.evaluate('document.documentElement.scrollWidth'),'panel_visible':page.locator('#sidebar').is_visible(),'panel':page.locator('#sidebar-items').inner_text() if page.locator('#sidebar').is_visible() else '', 'error':page.locator('#error').inner_text() if page.locator('#error').is_visible() else '', 'error_accessible':page.locator('#error').get_attribute('role')=='alert' or page.locator('#error').get_attribute('aria-live') is not None,'executed':page.evaluate('Boolean(window.__EXECUTED)'),'injected_elements':page.locator('#summary img, #drivers img, #vehicles img, #sidebar-items img, #summary script, #drivers script').count(),'requests':list(requests),'page_errors':list(errors)}
  rows=[]
  for op in r.get('operations',[{'op':'observe'}]):
   result=None
   if op['op']=='click':page.locator(op['selector']).click()
   elif op['op']=='dispatch':result=page.evaluate('(a)=>window.dashboard.dispatch(a)',op.get('action'))
   elif op['op']=='resize':page.set_viewport_size({'width':op['width'],'height':op.get('height',900)})
   elif op['op'] not in ('observe','capture'):raise ValueError('unsupported observation')
   page.wait_for_timeout(60);row=observe();row['dispatch_result']=result
   if op['op']=='capture':row['png']=base64.b64encode(page.screenshot(full_page=True)).decode()
   rows.append(row)
  browser.close();print(json.dumps({'observations':rows}))
finally:server.shutdown();server.server_close()
