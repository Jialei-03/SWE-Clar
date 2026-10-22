import os,sys,json,io,tempfile,subprocess,select,base64,concurrent.futures,re,unicodedata
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from decimal import Decimal,ROUND_HALF_UP
from pypdf import PdfReader
from playwright.sync_api import sync_playwright,expect
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'));WHITE={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'}
def assert_report_text(text,inputs,outputs):
 text=unicodedata.normalize('NFKC',text).lower()
 # Compare numeric values without freezing thousands separators or decimal padding.
 numbers={Decimal(x.replace(',','')) for x in re.findall(r'(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w.])',text)}
 for value in [*inputs.values(),*outputs.values()]:assert Decimal(str(value)) in numbers,(value,text)
 assert re.search(r'\b(?:sq\.?\s*ft|square\s+(?:feet|foot)|ft\s*(?:2|\^2))\b',text),text
 assert re.search(r'\b(?:sq\.?\s*m|square\s+met(?:re|er)s?|m\s*(?:2|\^2))\b',text),text

def assert_report(raw,inputs,outputs):
 pages=PdfReader(io.BytesIO(raw)).pages;assert pages
 assert_report_text(' '.join(p.extract_text() or '' for p in pages),inputs,outputs)
def run():
 os.environ['REPORT_PRIVATE_SENTINEL']='private-calculator-context'
 if not Path('/public_tests/browser_launcher.py').is_file() or not Path('/public_tests/invoke.py').is_file():return {'harness_ok':False,'results':[],'error':'Missing public helpers'}
 with tempfile.TemporaryDirectory() as tmp:
  folder=Path(tmp);folder.chmod(0o777);log=(folder/'server.log').open('w');server=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,user=1000,group=1000,extra_groups=[],env={**WHITE,'PORT':'0'},stdout=subprocess.PIPE,stderr=log,text=True)
  try:
   if not select.select([server.stdout],[],[],10)[0]:raise AssertionError('Candidate server startup failed')
   base='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port'])
   def request(path,value=None):
    q=Request(base+path,data=json.dumps(value).encode() if value is not None else None,headers={'Content-Type':'application/json'})
    try:r=urlopen(q,timeout=10)
    except HTTPError as e:r=e
    with r:return r.status,r.read(),dict(r.headers)
   def calculate(v):
    status,data,_=request('/calculate',v);assert status==200;return json.loads(data)
   def expected(v):
    d={k:Decimal(str(x)) for k,x in v.items()};rounding=lambda n:float(n.quantize(Decimal('.01'),rounding=ROUND_HALF_UP));return {'land_area_sqm':rounding(d['land_area_sqft']*Decimal('.092903')),'site_area_sqm':rounding(d['site_area_sqft']*Decimal('.092903')),'gross_floor_area_sqft':rounding((d['land_area_sqft']+d['site_area_sqft'])*d['plot_ratio'])}
   samples=[{'land_area_sqft':n,'site_area_sqft':n+7.125,'plot_ratio':1.5} for n in [0,1,17.375,5000,1234.5]]
   checks=[]
   def check1():
    v=samples[2];p=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(ROOT),'values':v}),env=WHITE,user=1000,group=1000,extra_groups=[],capture_output=True,text=True,check=True);r=json.loads(p.stdout);assert r['after']==v and r['value']['inputs']==v
    with concurrent.futures.ThreadPoolExecutor(4) as pool:rows=list(pool.map(calculate,samples))
    for v,r in zip(samples,rows):assert r['inputs']==v
    for path in ['/calculator.py','/report.py','/server.py','/../calculator.py']:
     status,_,_=request(path);assert status>=400
   def check2():
    for v in samples:
     r=calculate(v);e=expected(v);assert all(r['converted'].get(k)==e[k] for k in ['land_area_sqm','site_area_sqm'])
   def check3():
    for v in samples:assert calculate(v)['result']['gross_floor_area_sqft']==expected(v)['gross_floor_area_sqft']
   def check4():
    v=samples[2];r=calculate(v);assert all(r['summary'].get(k)==value for k,value in {**r['converted'],**r['result']}.items())
    status,raw,headers=request('/report',v);assert status==200 and 'application/pdf' in {k.lower():v for k,v in headers.items()}.get('content-type','');assert_report(raw,v,expected(v))
    if Path('/private/evidence').is_dir():Path('/private/evidence/report.pdf').write_bytes(raw)
    browser_checks(4,v)
   def browser_checks(ru,v):
    with sync_playwright() as p:
     proof=folder/'browser-proof.json';browser=p.chromium.launch(executable_path='/public_tests/browser_launcher.py',headless=True,downloads_path=str(folder),env={'PATH':WHITE['PATH'],'HOME':'/tmp','CLARSWE_BROWSER_BINARY':p.chromium.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
     try:
      identity=json.loads(proof.read_text());assert identity['uid']==1000 and identity['cap_eff']==0 and 'REPORT_PRIVATE_SENTINEL' not in identity['environment_keys']
      page=browser.new_page(viewport={'width':390,'height':844},accept_downloads=True);page.goto(base)
      for k,x in v.items():page.locator('[name='+k+']').fill(str(x))
      page.get_by_role('button',name='Calculate',exact=True).click();expect(page.locator('#results')).to_be_visible()
      if ru==4:
       for current in [v,{'land_area_sqft':231.25,'site_area_sqft':87.5,'plot_ratio':2.75}]:
        for k,x in current.items():page.locator('[name='+k+']').fill(str(x))
        page.get_by_role('button',name='Calculate',exact=True).click()
        for k,x in expected(current).items():expect(page.locator('[data-field='+k+']')).to_have_text(f'{x:.2f}')
        with page.expect_download() as d:page.get_by_role('button',name='Download PDF').click()
        path=d.value.path();read=subprocess.run([sys.executable,'-I','-c','import sys,base64;print(base64.b64encode(open(sys.argv[1],"rb").read()).decode())',str(path)],env=WHITE,user=1000,group=1000,extra_groups=[],capture_output=True,text=True,check=True);assert_report(base64.b64decode(read.stdout),current,expected(current))
       assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');image=page.screenshot(path=str(folder/'calculator.png'))
       if Path('/private/evidence').is_dir():Path('/private/evidence/calculator.png').write_bytes(image)
      else:
       before=[page.locator('[name='+k+']').input_value() for k in v];page.once('dialog',lambda d:d.dismiss());page.locator('#reset').click();assert [page.locator('[name='+k+']').input_value() for k in v]==before;expect(page.locator('#results')).to_be_visible()
       page.once('dialog',lambda d:d.accept());page.locator('#reset').click();expect(page.locator('#results')).to_be_hidden();assert all(page.locator('[name='+k+']').input_value()=='' for k in v)
       for k,x in v.items():page.locator('[name='+k+']').fill(str(x))
       page.get_by_role('button',name='Calculate',exact=True).click();expect(page.locator('#results')).to_be_visible();page.route('**/calculate',lambda r:r.fulfill(status=400,content_type='application/json',body='{"error":"invalid_input"}'));page.get_by_role('button',name='Calculate',exact=True).click();expect(page.locator('#results')).to_be_hidden()
     finally:browser.close()
   def check5():
    invalid=[{},dict(samples[0],plot_ratio=True),dict(samples[0],plot_ratio=-1),dict(samples[0],plot_ratio='1'),dict(samples[0],plot_ratio=float('inf')),dict(samples[0],plot_ratio=1e308)]
    for v in invalid:
     for path in ['/calculate','/report']:
      status,raw,_=request(path,v);assert status==400 and json.loads(raw).get('error')=='invalid_input' and not raw.startswith(b'%PDF')
    browser_checks(5,samples[1])
   for i,check in enumerate([check1,check2,check3,check4,check5],1):
    try:check();checks.append({'ru_id':f'RU-{i:03}','passed':True})
    except Exception as e:checks.append({'ru_id':f'RU-{i:03}','passed':False,'detail':__import__('traceback').format_exc()})
   return {'harness_ok':True,'results':checks}
  finally:server.terminate();server.wait(timeout=10);log.close()
if __name__=='__main__':
 try:print(json.dumps(run()))
 except Exception as e:print(json.dumps({'harness_ok':True,'results':[{'ru_id':f'RU-{i:03}','passed':False,'detail':str(e)} for i in range(1,6)]}))
