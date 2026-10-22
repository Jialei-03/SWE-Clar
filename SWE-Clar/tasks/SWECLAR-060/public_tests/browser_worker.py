"""Generic real browser observations; no private gameplay assertions."""
import base64,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
r=json.load(sys.stdin);rows=[]
with tempfile.TemporaryDirectory(prefix='arena-browser-') as temp:
 root=Path(temp)/'project';shutil.copytree(r['project'],root,ignore=shutil.ignore_patterns('.git','__pycache__'))
 if 'initial' in r:(root/'scenario.json').write_text(json.dumps(r['initial']))
 process=subprocess.Popen([sys.executable,str(root/'server.py'),'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,cwd=root)
 try:
  line=process.stdout.readline();base='http://127.0.0.1:'+str(json.loads(line)['port'])
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1100,'height':950});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(base);page.locator('#status').wait_for();page.wait_for_function("document.querySelector('#status').textContent !== 'Loading arena'")
   for op in r['operations']:
    row={'op':op['op']}
    try:
     if op['op']=='click':
      if op.get('response'):
       with page.expect_response(lambda response:response.url==base+op['response']) as pending:page.locator(op['selector']).click()
       response=pending.value;response.finished();row['response_status']=response.status
      else:page.locator(op['selector']).click()
     elif op['op']=='move':
      canvas=page.locator('#arena');canvas.focus();old=canvas.evaluate('(c)=>c.toDataURL()');page.keyboard.down(op['key'])
      try:page.wait_for_function("old=>document.querySelector('#arena').toDataURL()!==old",arg=old,timeout=5000)
      finally:page.keyboard.up(op['key'])
     elif op['op']=='http':
      response=page.request.fetch(base+op['path'],method=op.get('method','GET'),data=op.get('data'));row['response_status']=response.status
      try:row['response']=response.json()
      except Exception:row['response_text']=response.text()
     elif op['op']=='reload':page.reload();page.wait_for_function("document.querySelector('#status').textContent !== 'Loading arena'")
     elif op['op']=='select':page.locator(op['selector']).select_option(op['value'])
     elif op['op'] not in {'inspect','capture'}:raise ValueError('Unknown public browser operation')
     page.wait_for_timeout(30)
     row['state']=page.request.get(base+'/state').json();row['text']=page.locator('body').inner_text();row['inventory']=page.locator('#inventory').inner_text();row['creatures']=page.locator('#creatures').inner_text();row['options']=page.locator('#recipe option').evaluate_all('(xs)=>xs.map(x=>({value:x.value,text:x.textContent}))');row['canvas']=base64.b64encode(page.locator('#arena').screenshot()).decode()
     if op['op']=='capture':row['png']=base64.b64encode(page.screenshot(full_page=True)).decode()
     row['page_errors']=list(errors)
    except Exception as e:row['operation_error']=type(e).__name__+': '+str(e)
    rows.append(row)
   browser.close()
 finally:
  process.terminate()
  try:process.wait(timeout=5)
  except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
print(json.dumps({'observations':rows}))
