"""Generic real browser controls and observations; no private gameplay assertions."""
import base64,datetime,json,subprocess,sys,tempfile,shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
r=json.load(sys.stdin);rows=[]
with tempfile.TemporaryDirectory(prefix='portal-browser-') as temp:
 root=Path(temp)/'project';shutil.copytree(r['project'],root,ignore=shutil.ignore_patterns('__pycache__','.git'))
 if 'initial' in r:(root/'scenario.json').write_text(json.dumps(r['initial']))
 proc=subprocess.Popen([sys.executable,str(root/'server.py'),'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,cwd=root)
 try:
  base='http://127.0.0.1:'+str(json.loads(proc.stdout.readline())['port'])
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader']);page=browser.new_page(viewport={'width':1280,'height':800});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   controlled=r.get('controlled_clock',False)
   if controlled:
    now=datetime.datetime(2028,1,1,tzinfo=datetime.timezone.utc);page.clock.install(time=now);page.clock.pause_at(now)
   page.goto(base+'/game');page.locator('body[data-ready="true"]').wait_for()
   for operation in r['operations']:
    row={'op':operation['op']}
    try:
     op=operation['op']
     if op=='click':
      if operation.get('response',True):
       with page.expect_response(lambda resp:resp.url==base+'/action') as pending:page.locator(operation['selector']).click()
       pending.value.finished()
      else:page.locator(operation['selector']).click()
      if controlled:page.clock.run_for(40)
      else:page.wait_for_timeout(40)
     elif op=='wait':
      if controlled:page.clock.run_for(operation['milliseconds'])
      else:page.wait_for_timeout(operation['milliseconds'])
     elif op=='select':page.locator(operation['selector']).select_option(operation['value'])
     elif op=='http':
      resp=page.request.fetch(base+operation['path'],method=operation.get('method','GET'),data=operation.get('data'));row['response_status']=resp.status;row['response']=resp.json()
     elif op not in ['inspect','capture']:raise ValueError('Unknown public operation')
     row['state']=page.request.get(base+'/state').json();row['hud']=page.locator('#hud').inner_text();row['text']=page.locator('body').inner_text();row['targets']=page.locator('#target option').evaluate_all('(xs)=>xs.map(x=>({value:x.value,text:x.textContent}))');row['webgl']=page.locator('#scene').evaluate('(c)=>{const g=c.getContext("webgl");return {present:!!g,depth:g&&g.getContextAttributes().depth,renderer:c.dataset.renderer}}');row['canvas']=base64.b64encode(page.locator('#scene').screenshot()).decode();row['page_errors']=errors[:]
     if op=='capture':row['png']=base64.b64encode(page.screenshot(full_page=True)).decode()
    except Exception as e:row['operation_error']=type(e).__name__+': '+str(e)
    rows.append(row)
   browser.close()
 finally:
  proc.terminate()
  try:proc.wait(timeout=5)
  except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
print(json.dumps({'observations':rows}))
