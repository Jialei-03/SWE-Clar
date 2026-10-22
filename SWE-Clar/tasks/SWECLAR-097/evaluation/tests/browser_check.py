import os,json,base64
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

def marker_pixel_bounds(browser,before,without,point):
 # Decode browser-captured PNGs in a separate verifier-owned blank context.
 # This uses the already required Chromium, not an undeclared image package.
 decoder=browser.new_page()
 try:
  box=decoder.evaluate('''async ([before,after])=>{
   const read=async raw=>{const image=new Image();image.src='data:image/png;base64,'+raw;await image.decode();
     const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;
     const context=canvas.getContext('2d');context.drawImage(image,0,0);
     return {width:image.width,height:image.height,data:context.getImageData(0,0,image.width,image.height).data}};
   const a=await read(before),b=await read(after);
   if(a.width!==b.width||a.height!==b.height)throw Error('Screenshot dimensions changed');
   let left=a.width,top=a.height,right=-1,bottom=-1;
   for(let y=0;y<a.height;y++)for(let x=0;x<a.width;x++){const i=(y*a.width+x)*4;
    if(a.data[i]!==b.data[i]||a.data[i+1]!==b.data[i+1]||a.data[i+2]!==b.data[i+2]){
     left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y)}}
   return right<0?null:[left,top,right+1,bottom+1];
  }''',[base64.b64encode(before).decode(),base64.b64encode(without).decode()])
 finally:decoder.close()
 assert box and box[0]-3<=point['x']<=box[2]+3 and box[1]-3<=point['y']<=box[3]+3, {'point':point,'rendered_difference':box}
 return box

def exercise(a):
 os.environ['REPORT_PRIVATE_SENTINEL']='private-date-context';r={'errors':[],'remote':[],'layouts':[],'operation_failures':[]}
 with sync_playwright() as p:
  proof=a.root/'browser-proof.json';browser=p.chromium.launch(headless=True,executable_path='/public_tests/browser_launcher.py',env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','CLARSWE_BROWSER_BINARY':p.chromium.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
  try:
   identity=json.loads(proof.read_text());assert identity['uid']==1000 and identity['cap_eff']==0 and 'REPORT_PRIVATE_SENTINEL' not in identity['environment_keys']
   page=browser.new_page(viewport={'width':390,'height':844});page.set_default_timeout(5000);page.on('pageerror',lambda e:r['errors'].append(str(e)));page.on('request',lambda q:r['remote'].append(q.url) if not q.url.startswith(a.url) else None);page.goto(a.url);page.locator('#username').fill('browser');page.locator('#password').fill('synthetic-pass');page.get_by_role('button',name='Sign in').click();expect(page.locator('#workspace')).to_be_visible();page.wait_for_function('typeof map!=="undefined" && map instanceof L.Map')
   center=lambda:page.evaluate('({lat:map.getCenter().lat,lng:map.getCenter().lng})')
   r['initial']=center()
   for width in [390,1100]:page.set_viewport_size({'width':width,'height':844});page.wait_for_timeout(100);r['layouts'].append(page.evaluate('({overflow:document.documentElement.scrollWidth>innerWidth+1,height:document.querySelector("#map").getBoundingClientRect().height})'))
   page.locator('#query').fill('ClEaR');page.get_by_role('button',name='Search',exact=True).click();expect(page.locator('#places button')).to_have_count(2);r['venues']=page.locator('#places button').all_text_contents();page.get_by_role('button',name='Clear coffee',exact=True).click();r['center']=center()
   # A Canvas circle has no per-marker DOM element. Bring the selected point
   # into the observation viewport and verify actual rendered pixels instead
   # of prescribing SVG. Initial/return location behavior is checked separately.
   page.locator('#map').scroll_into_view_if_needed()
   page.evaluate('()=>map.panTo(marker.getLatLng(),{animate:false})');page.wait_for_timeout(350)
   geometry=page.evaluate('''()=>{const ll=marker.getLatLng(),point=map.latLngToContainerPoint(ll);let paths=0;map.eachLayer(l=>{if(l instanceof L.Path)paths++});return {lat:ll.lat,lng:ll.lng,x:point.x,y:point.y,paths,leaflet:L.version}}''')
   canvas=page.locator('#map');before=canvas.screenshot()
   page.evaluate('()=>map.removeLayer(marker)');page.wait_for_timeout(150);without=canvas.screenshot()
   page.evaluate('()=>marker.addTo(map)');page.wait_for_timeout(150)
   box=marker_pixel_bounds(browser,before,without,geometry);geometry['width']=box[2]-box[0]
   r['marker']=geometry;r['paths']=geometry['paths']
   r['creditInitially']=page.locator('#credit').is_enabled()
   def click(button,path):
    with page.expect_response(lambda q:q.url.endswith(path) and q.request.method=='POST'):page.locator(button).click()
    page.wait_for_timeout(150)
   click('#credit','/credit');r['creditBalance']=page.locator('#balance').inner_text();r['creditDate']=page.locator('#dates').inner_text();r['noCredit']=page.locator('#credit').is_disabled()
   page.locator('#products').select_option('three');before=int(page.locator('#balance').get_attribute('data-credits'));count=page.locator('#dates p').count();click('#purchase','/purchase');r['purchaseDelta']=int(page.locator('#balance').get_attribute('data-credits'))-before;r['purchaseDateDelta']=page.locator('#dates p').count()-count
   before=int(page.locator('#balance').get_attribute('data-credits'));count=page.locator('#dates p').count();a.provider.fault='lost_response';click('#purchase','/purchase');click('#purchase','/purchase');r['retryDelta']=int(page.locator('#balance').get_attribute('data-credits'))-before;r['retryDateDelta']=page.locator('#dates p').count()-count
   page.locator('#location').click();r['returnCenter']=center();image=page.screenshot(path=str(a.root/'date-map.png'))
   if Path('/private/evidence').is_dir():Path('/private/evidence/date-map.png').write_bytes(image)
  finally:browser.close();a.provider.fault=None
 return r
