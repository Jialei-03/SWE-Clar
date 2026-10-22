import json,os,io
from PIL import Image,ImageChops
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

def exercise(a,kind):
 with sync_playwright() as p:
  folder=a.root/'browser';folder.mkdir(exist_ok=True);folder.chmod(0o777);proof=folder/'process.json'
  browser=p.chromium.launch(headless=True,executable_path='/public_tests/browser_launcher.py',downloads_path=str(folder),env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','CLARSWE_BROWSER_BINARY':p.chromium.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
  try:
   identity=json.loads(proof.read_text());assert identity['uid']==1000 and identity['cap_eff']==0 and 'MEAL_PRIVATE_SENTINEL' not in identity['environment_keys']
   fields=dict(x.split(':',1) for x in Path('/proc/%s/status'%identity['pid']).read_text().splitlines() if ':' in x);assert set(fields['Uid'].split())=={'1000'} and int(fields['CapEff'],16)==0
   page=browser.new_page(viewport={'width':1100,'height':900});page.set_default_timeout(6000)
   def instrument(route):
    response=route.fetch();prefix="L.Map.addInitHook(function(){window.__mapObservation=this;});"
    route.fulfill(response=response,body=prefix+response.text())
   page.route('**/app.js',instrument);page.goto(a.url)
   def connect(user):
    page.get_by_label('Access token').fill('synthetic-'+user);page.get_by_role('button',name='Connect',exact=True).click()
   connect('a');expect(page.locator('#feed article')).to_have_count(2)
   assert page.locator('#feed article').evaluate_all('(xs)=>xs.map(x=>x.dataset.post)')==['post-b','post-a']
   page.wait_for_function("()=>[...document.querySelectorAll('#feed img')].every(i=>i.naturalWidth===120&&i.naturalHeight===90)")
   values=page.locator('#feed img').first.evaluate("im=>{let c=document.createElement('canvas');c.width=120;c.height=90;let x=c.getContext('2d');x.drawImage(im,0,0);return [...x.getImageData(0,0,1,1).data]}");assert values[:3]==[245,235,214]
   if kind=='save':
    expect(page.locator('[data-post="post-a"] button')).to_have_count(0)
    page.locator('[data-post="post-b"]').get_by_role('button',name='Save',exact=True).click();expect(page.locator('[data-post="post-b"]').get_by_role('button',name='Unsave',exact=True)).to_be_visible()
    page.locator('[data-post="post-b"]').get_by_role('button',name='Unsave',exact=True).click();expect(page.locator('[data-post="post-b"]').get_by_role('button',name='Save',exact=True)).to_be_visible()
   if kind=='feed':
    page.get_by_label('Photo',exact=True).set_input_files(str(a.photo));page.get_by_label('Food',exact=True).fill('Browser meal');page.get_by_label('Caption',exact=True).fill('Actual photo upload')
    with page.expect_response(lambda r:r.url.endswith('/post') and r.request.method=='POST') as response:page.get_by_role('button',name='Post meal',exact=True).click()
    assert 200<=response.value.status<300;expect(page.locator('#feed article')).to_have_count(3)
    delayed=[]
    def delay(route):
     if route.request.headers.get('authorization')=='Bearer synthetic-a':delayed.append(route)
     else:route.continue_()
    page.route('**/feed',delay);connect('a');page.wait_for_timeout(150);assert delayed;connect('c');expect(page.locator('#feed article')).to_have_count(1);expect(page.locator('[data-post="post-c"]')).to_be_visible()
    for route in delayed:route.continue_()
    page.wait_for_timeout(150);assert page.locator('#feed article').evaluate_all('(xs)=>xs.map(x=>x.dataset.post)')==['post-c']
   if kind=='map':
    for mode,lat,lon in [('personal',0.001,0.002),('friends',0.002,0.003)]:
     page.locator('#mode').select_option(mode)
     page.wait_for_function("([lat,lon])=>{let m=window.__mapObservation;if(!m)return false;let a=[];m.eachLayer(l=>{if(typeof l.getLatLng==='function')a.push(l)});return a.length===1&&a[0].getLatLng().lat===lat&&a[0].getLatLng().lng===lon}",arg=[lat,lon])
     for width in [1100,390]:
      page.set_viewport_size({'width':width,'height':844});page.wait_for_timeout(150)
      # Screenshot scrolls its target into view. Do that before observing map
      # coordinates, so a resize/scroll-induced layout cannot stale the anchor.
      page.locator('#map').scroll_into_view_if_needed()
      page.wait_for_timeout(350)
      result=page.evaluate("""()=>{let m=window.__mapObservation,a=[];m.eachLayer(l=>{if(typeof l.getLatLng==='function'){let p=m.latLngToContainerPoint(l.getLatLng());a.push({x:p.x,y:p.y,visible:p.x>=0&&p.y>=0&&p.x<=m.getSize().x&&p.y<=m.getSize().y})}});return {points:a,overflow:document.documentElement.scrollWidth>innerWidth+1}}""")
      assert not result['overflow'] and len(result['points'])==1
      point=result['points'][0];assert point['visible'],result
      # Removing the actual layer must remove rendered pixels at its geographic
      # anchor. This works for icon markers, SVG paths and Canvas renderers.
      canvas=page.locator('#map');before=canvas.screenshot()
      page.evaluate("()=>{const m=window.__mapObservation;m.eachLayer(l=>{if(typeof l.getLatLng==='function')window.__observedPoint=l});m.removeLayer(window.__observedPoint)}")
      page.wait_for_timeout(100);without=canvas.screenshot()
      page.evaluate('()=>window.__observedPoint.addTo(window.__mapObservation)');page.wait_for_timeout(100)
      with Image.open(io.BytesIO(before)) as one,Image.open(io.BytesIO(without)) as two:
       box=ImageChops.difference(one.convert('RGB'),two.convert('RGB')).getbbox()
      assert box and box[0]-3<=point['x']<=box[2]+3 and box[1]-3<=point['y']<=box[3]+3,{'point':point,'pixel_difference':box,'mode':mode,'width':width,'screenshot_size':one.size,'map_bounds':canvas.bounding_box()}
  finally:browser.close()
