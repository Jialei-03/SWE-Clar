"""Generic real WebGL/iframe browser operations; no hidden puzzle assertions."""
import base64,json,subprocess,sys,tempfile,shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
r=json.load(sys.stdin);rows=[]
with tempfile.TemporaryDirectory(prefix='escape-browser-') as temp:
 root=Path(temp)/'project';shutil.copytree(r['project'],root,ignore=shutil.ignore_patterns('__pycache__','.git'))
 if 'initial' in r:(root/'scenario.json').write_text(json.dumps(r['initial']))
 proc=subprocess.Popen([sys.executable,str(root/'server.py'),'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,cwd=root)
 try:
  base='http://127.0.0.1:'+str(json.loads(proc.stdout.readline())['port'])
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,args=['--no-sandbox','--enable-unsafe-swiftshader']);page=browser.new_page(viewport=r.get('viewport',{'width':1280,'height':720}));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(base+r.get('path','/game'));frame=page.frame_locator('iframe') if r.get('path')=='/embed' else page;frame.locator('body[data-ready="true"]').wait_for(timeout=12000)
   for operation in r['operations']:
    row={'op':operation['op']}
    try:
     op=operation['op']
     if op=='fill':frame.locator(operation['selector']).fill(operation['value'])
     elif op=='click':
      with page.expect_response(lambda resp:resp.url==base+'/action') as pending:frame.locator(operation['selector']).click()
      pending.value.finished();page.wait_for_timeout(40)
     elif op=='resize':
      with page.expect_response(lambda resp:resp.url==base+'/action') as pending:page.set_viewport_size({'width':operation['width'],'height':operation['height']})
      pending.value.finished();page.wait_for_timeout(50)
     elif op=='locale':frame.locator('#locale').select_option(operation['value']);frame.locator('body[data-localized="true"]').wait_for();page.wait_for_timeout(40)
     elif op=='http':
      resp=page.request.fetch(base+operation['path'],method=operation.get('method','GET'),data=operation.get('data'));row['response_status']=resp.status;row['response']=resp.json()
     elif op not in ['inspect','capture']:raise ValueError('Unknown public operation')
     row['state']=page.request.get(base+'/state').json();row['text']=frame.locator('body').inner_text();row['rotate_visible']=frame.locator('#rotate').is_visible();row['room_inert']=frame.locator('#room').evaluate('(e)=>e.inert');row['exit_enabled']=frame.locator('#exit').is_enabled();row['completed']=frame.locator('#completion').is_visible();row['presentation']=frame.locator('body').get_attribute('data-presentation');row['labels']=frame.locator('[data-text]').evaluate_all('(xs)=>Object.fromEntries(xs.map(x=>[x.dataset.text,x.textContent]))');row['locks']=frame.locator('.lock').evaluate_all('(xs)=>xs.map(x=>({id:x.id,solved:x.dataset.solved}))');row['frame_count']=len(page.frames)
     row['webgl']=frame.locator('#scene').evaluate('(c)=>{const g=c.getContext("webgl");return {present:!!g,depth:g&&g.getContextAttributes().depth,renderer:c.dataset.renderer,width:c.getBoundingClientRect().width,height:c.getBoundingClientRect().height}}');row['canvas']=base64.b64encode(frame.locator('#scene').screenshot()).decode();row['page_errors']=errors[:]
     if op=='capture':row['png']=base64.b64encode(page.screenshot(full_page=True)).decode()
    except Exception as e:row['operation_error']=type(e).__name__+': '+str(e)
    rows.append(row)
   browser.close()
 finally:
  proc.terminate()
  try:proc.wait(timeout=5)
  except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
print(json.dumps({'observations':rows}))
