import os,sys,json,tempfile,subprocess,select
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

READY=False
def mobile_navigation(page,base):
 for width in [360,767]:
  page.set_viewport_size({'width':width,'height':900})
  for source,target in [('index.html','cookie-policy.html'),('cookie-policy.html','index.html')]:
   page.goto(base+'/'+source)
   button=page.get_by_role('button',name='Menu',exact=True);expect(button).to_be_visible()
   navigation=page.locator('#'+button.get_attribute('aria-controls'))
   expect(button).to_have_attribute('aria-expanded','false');expect(navigation).to_be_hidden()
   button.click();expect(button).to_have_attribute('aria-expanded','true');expect(navigation).to_be_visible()
   button.click();expect(button).to_have_attribute('aria-expanded','false');expect(navigation).to_be_hidden()
   button.click();navigation.locator('a[href="'+target+'"]').click();expect(page).to_have_url(base+'/'+target)

def run():
 global READY
 os.environ['REPORT_PRIVATE_SENTINEL']='private-layout-context';root=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
 if not all(Path('/public_tests',n).is_file() for n in ['browser_launcher.py','static_server.py']):return {'harness_ok':False,'results':[],'error':'Missing public browser launcher'}
 with tempfile.TemporaryDirectory() as tmp:
  folder=Path(tmp);folder.chmod(0o777);env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PORT':'0','PYTHONDONTWRITEBYTECODE':'1'};server=subprocess.Popen([sys.executable,'-I','/public_tests/static_server.py'],cwd=root,env=env,user=1000,group=1000,extra_groups=[],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
  try:
   assert select.select([server.stdout],[],[],10)[0];base='http://127.0.0.1:'+str(json.loads(server.stdout.readline())['port'])
   with sync_playwright() as p:
    proof=folder/'browser-proof.json';browser=p.chromium.launch(executable_path='/public_tests/browser_launcher.py',headless=True,env={'PATH':env['PATH'],'HOME':'/tmp','CLARSWE_BROWSER_BINARY':p.chromium.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
    try:
     identity=json.loads(proof.read_text());assert identity['uid']==1000 and identity['cap_eff']==0 and 'REPORT_PRIVATE_SENTINEL' not in identity['environment_keys']
     Path('/private/results').mkdir(parents=True,exist_ok=True)
     for kind,pid,record in [('browser',identity['pid'],identity),('service',server.pid,{'environment_keys':sorted(env)})]:
      status=dict(line.split(':',1) for line in Path('/proc/'+str(pid)+'/status').read_text().splitlines() if ':' in line);assert set(status['Uid'].split())=={'1000'} and int(status['CapEff'],16)==0;record.update(pid=pid,uid=1000,cap_eff=0,live_pid_verified=True)
      with open('/private/results/'+kind+'-isolation.jsonl','a') as out:out.write(json.dumps(record)+'\n')
     READY=True;page=browser.new_page();observations=[];remote=[];page.on('request',lambda r:remote.append(r.url) if not r.url.startswith(base) else None)
     for name in ['index.html','cookie-policy.html']:
      for width in [360,768,991,992,1180,1380,1920]:
       page.set_viewport_size({'width':width,'height':900});page.goto(base+'/'+name);page.locator('main').wait_for()
       data=page.evaluate('''()=>{const box=e=>{let r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};return {shells:[...document.querySelectorAll('.shell')].map(box),offers:[...document.querySelectorAll('.offer')].map(e=>({card:box(e),shell:e.closest('.shell')?box(e.closest('.shell')):null,label:box(e.querySelector('.offer-label')),metrics:box(e.querySelector('.offer-metrics')),logo:box(e.querySelector('img'))})),hero:document.querySelector('.hero-art')?box(document.querySelector('.hero-art')):null,overflow:document.documentElement.scrollWidth>innerWidth+1,clip:[getComputedStyle(document.documentElement).overflowX,getComputedStyle(document.body).overflowX].some(v=>['hidden','clip'].includes(v)),paragraphs:[...document.querySelectorAll('p')].map(e=>({size:getComputedStyle(e).fontSize,line:getComputedStyle(e).lineHeight,font:getComputedStyle(e).fontFamily})),images:[...document.images].map(i=>i.complete&&i.naturalWidth>0)}}''');observations.append({'page':name,'width':width,**data})
       if width in [360,1180]:page.screenshot(path=str(folder/(name+str(width)+'.png')),full_page=True)
     page.goto(base+'/cookie-policy.html');page.locator('a[href="index.html"]:visible').first.click();expect(page).to_have_url(base+'/index.html')
     def check1():
      mobile_navigation(page,base)
      assert not remote and all(all(r['images']) for r in observations);assert all(len(r['offers'])==3 for r in observations if r['page']=='index.html')
     def check2():
      for r in observations:
       if not 992<=r['width']<=1380:continue
       for shell in r['shells']:assert shell['w']<=1241 and abs(shell['x']-(r['width']-shell['w'])/2)<2
       assert r['shells'],'Missing content shell'
       if r['page']=='index.html':assert r['hero'] and r['hero']['w']>0 and r['hero']['h']>0,'Desktop hero removed'
       for offer in r['offers']:
        shell=offer['shell'];assert shell and offer['card']['x']>=shell['x']-1 and offer['card']['right']<=shell['right']+1,'Offer extends outside content shell'
        c,l,m,logo=[offer[k] for k in ['card','label','metrics','logo']];assert l['right']+.5<=m['x'] and logo['w']>0 and logo['x']>=c['x'] and m['right']<=c['right']+1
     def check3():assert all(not r['overflow'] or r['clip'] for r in observations)
     def check4():
      for r in observations:
       if r['page']!='index.html' or r['width']>=992:continue
       assert r['hero'] is None or r['hero']['w']==0 or r['hero']['h']==0
       for offer in r['offers']:
        c,l,m=[offer[k] for k in ['card','label','metrics']];assert c['x']>=-1 and c['right']<=r['width']+1 and l['bottom']<=m['y']+1
     rows=[]
     for i,check in enumerate([check1,check2,check3,check4],1):
      try:check();passed,detail=True,''
      except Exception as e:passed,detail=False,str(e)
      rows.append({'ru_id':f'RU-{i:03}','passed':passed,'detail':detail})
     if Path('/private/evidence').is_dir():Path('/private/evidence/layout-observations.json').write_text(json.dumps(observations))
     return {'harness_ok':True,'results':rows}
    finally:browser.close()
  finally:server.terminate();server.wait(timeout=10)
if __name__=='__main__':
 try:print(json.dumps(run()))
 except Exception as e:print(json.dumps({'harness_ok':READY,'results':[{'ru_id':f'RU-{i:03}','passed':False,'detail':str(e)} for i in range(1,5)] if READY else [],'error':str(e)}))
