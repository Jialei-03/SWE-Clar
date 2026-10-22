"""Protected per-RU HTTP and real Linux browser acceptance."""
import contextlib,traceback,os,sys,json,tempfile,subprocess,select,base64,time,io,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from PIL import Image
sys.path.insert(0,'/public_tests')
from photo_fixtures import configuration,jpeg
from backend_contract import evaluate_backend
ROOT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))
WHITE={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'}
def assert_photo_membership(timeline_urls,grid_urls,records,late):
 from urllib.parse import urlsplit
 path=lambda url:urlsplit(url).path
 timeline=[path(u) for u in timeline_urls];grid=[path(u) for u in grid_urls]
 assert sorted(timeline)==sorted(path(r['url']) for r in records), {'timeline':timeline,'expected':records}
 assert sorted(grid)==sorted(path(r['url']) for r in records if r['eligible']), {'grid':grid,'expected':records}
 assert path(late['url']) in timeline and path(late['url']) not in grid

def run():
 with contextlib.nullcontext(tempfile.mkdtemp(prefix="photo-verifier-")) as tmp:
  folder=Path(tmp);folder.chmod(0o777);config=folder/'config.json';config.write_text(json.dumps(configuration()));config.chmod(0o644);server=None;port=0
  def start():
   nonlocal server,port
   server=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,user=1000,group=1000,extra_groups=[],env={**WHITE,'PORT':str(port),'PHOTO_CONFIG':str(config),'PHOTO_DATABASE':str(folder/'state.db'),'PHOTO_ASSETS':str(folder/'images')},stdout=subprocess.PIPE,stderr=(folder/'server.log').open('a'),text=True)
   assert select.select([server.stdout],[],[],12)[0],'Server startup timeout';port=int(server.stdout.readline());return 'http://127.0.0.1:'+str(port)
  def restart():
   server.terminate();server.wait(timeout=10);return start()
  try:
   base=start();backend=evaluate_backend(base,restart);results={int(k):v for k,v in backend['results'].items()};evidence={'backend':backend}
   def check(i,fn):
    try:fn()
    except Exception as e:results[i]={'passed':False,'detail':traceback.format_exc()}
   with sync_playwright() as pw:
    proof=folder/'browser-proof.json';browser=pw.chromium.launch(executable_path='/public_tests/browser_launcher.py',headless=True,env={**WHITE,'CLARSWE_BROWSER_BINARY':pw.chromium.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
    try:
     identity=json.loads(proof.read_text());assert identity['uid']==1000 and identity['cap_eff']==0;evidence['browser_identity']=identity
     page=browser.new_page(viewport={'width':700,'height':1000})
     # Observe real HTTP-to-Blob provenance. Authenticated fetch + object URL
     # is a valid image delivery strategy; a blob URL is not an API path.
     page.add_init_script("""(() => {
       const origins=new WeakMap(), urls=new Map();
       const read=Response.prototype.blob, create=URL.createObjectURL;
       Response.prototype.blob=async function(...args) {
         const blob=await read.apply(this,args); origins.set(blob,this.url); return blob;
       };
       URL.createObjectURL=function(blob) {
         const url=create.call(this,blob); if(origins.has(blob)) urls.set(url,origins.get(blob)); return url;
       };
       Object.defineProperty(window,'__observedPhotoSource',{value:url=>urls.get(url)||url});
     })();""")
     page.goto(base)
     def login(user):
      page.locator('#login [name=user]').fill(user)
      with page.expect_response(base+'/rooms'):
       page.get_by_role('button',name='Sign in',exact=True).click()
      expect(page.locator('main')).to_be_visible();expect(page.locator('#room')).to_have_value('room-one')
      # Showing the room precedes its async photo refresh. Do not issue a
      # second refresh/login while the previous interaction still downloads.
      page.wait_for_load_state('networkidle')
     def interface():
      login('user-a');page.locator('#create [name=caption]').fill('Browser color cards');page.get_by_role('button',name='Create request',exact=True).click();expect(page.locator('#requests button').filter(has_text='Browser color cards')).to_have_count(1)
      rowid=page.locator('#route [name=request]').input_value();assert rowid;evidence['browser_request']=rowid
      login('user-b');page.locator('#requests button').filter(has_text='Browser color cards').click();expect(page.locator('#selected')).to_contain_text(rowid);time.sleep(3.2)
      page.locator('#upload [name=image]').set_input_files({'name':'synthetic.jpg','mimeType':'image/jpeg','buffer':jpeg()});page.get_by_role('button',name='Upload photo',exact=True).click();expect(page.locator('#timeline figcaption').filter(has_text='Browser color cards')).to_have_count(1)
      image=page.locator('#timeline figure').filter(has_text='Browser color cards').locator('img');assert image.evaluate('(img)=>img.complete && img.naturalWidth===96 && img.naturalHeight===80');raw=image.screenshot();im=Image.open(io.BytesIO(raw)).convert('RGB');x,y=im.size;assert max(abs(a-b) for a,b in zip(im.getpixel((int(x*.2),int(y*.4))),(220,35,20)))<40
      page.reload();login('user-b');expect(page.locator('#timeline figcaption').filter(has_text='Browser color cards')).to_have_count(1)
     check(1,interface)
     def eligibility():
      login('user-b')
      token=json.load(urllib.request.urlopen(urllib.request.Request(base+'/login',data=json.dumps({'user':'user-b','password':'synthetic-passphrase'}).encode(),headers={'Content-Type':'application/json'})))['token']
      records=json.load(urllib.request.urlopen(urllib.request.Request(base+'/timeline?room=room-one',headers={'Authorization':'Bearer '+token})))
      page.get_by_role('button',name='Refresh',exact=True).click()
      page.wait_for_load_state('networkidle')
      # Capture both lists in one browser turn. Separate locator reads can
      # straddle an asynchronous refresh and observe an emptied container.
      # Wait for counts/decoding only, never for the expected membership:
      # a wrong photo with the right count must still fail the assertion.
      snapshot=page.wait_for_function("""({timelineCount,gridCount}) => {
        const timeline=[...document.querySelectorAll('#timeline img')];
        const grid=[...document.querySelectorAll('#grid img')];
        if(timeline.length!==timelineCount || grid.length!==gridCount ||
           [...timeline,...grid].some(n=>!n.complete || !n.naturalWidth)) return false;
        const urls=nodes=>nodes.map(n=>window.__observedPhotoSource(n.currentSrc||n.src));
        return {timeline:urls(timeline),grid:urls(grid)};
      }""",arg={'timelineCount':len(records),'gridCount':sum(bool(r['eligible']) for r in records)}).json_value()
      assert_photo_membership(snapshot['timeline'],snapshot['grid'],records,backend['evidence']['late_photo'])
     check(3,eligibility)
     def route():
      page.locator('#route [name=request]').fill('backend-image');page.get_by_role('button',name='Open route',exact=True).click();expect(page.locator('#route-result')).to_have_text('/rooms/room-one/requests/backend-image')
      page.locator('#route [name=request]').fill('unknown-browser-request');page.get_by_role('button',name='Open route',exact=True).click();expect(page.locator('#status')).to_contain_text('not_found')
     check(4,route)
     def contacts_grid():
      page.locator('#contact [name=numbers]').fill('+1 (202) 555-0100');page.get_by_role('button',name='Find contact',exact=True).click();expect(page.locator('#contact-result')).to_have_text('Added: user-a')
      # Supply three different real JPEGs via actual authenticated HTTP, without patching app state.
      def api(path,body,token=''):
       q=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token});return json.load(urllib.request.urlopen(q))
      tokens={u:api('/login',{'user':u,'password':'synthetic-passphrase'})['token'] for u in ['user-a','user-b','user-c','user-d']}
      api('/requests',{'id':'grid-challenge','room':'room-one','mode':'challenge','caption':'Three color cards'},tokens['user-a'])
      for u in ['user-b','user-c','user-d']:api('/open',{'request':'grid-challenge'},tokens[u])
      time.sleep(3.2)
      for i,u in enumerate(['user-b','user-c','user-d']):api('/respond',{'request':'grid-challenge','image':base64.b64encode(jpeg(i)).decode()},tokens[u])
      page.get_by_role('button',name='Refresh',exact=True).click();expect(page.locator('#grid figure').filter(has_text='Three color cards')).to_have_count(3)
      # All eligible images share the group grid. Choose an odd total by observing current server result.
      count=page.locator('#grid figure').count()
      if count%2==0:
       api('/requests',{'id':'extra-grid','room':'room-one','mode':'ask','caption':'Extra color card'},tokens['user-a']);api('/open',{'request':'extra-grid'},tokens['user-b']);time.sleep(3.2);api('/respond',{'request':'extra-grid','image':base64.b64encode(jpeg(1)).decode()},tokens['user-b']);page.get_by_role('button',name='Refresh',exact=True).click();expect(page.locator('#grid figure')).to_have_count(count+1)
      figures=page.locator('#grid figure');n=figures.count();assert n>=3 and n%2==1;bounds=[figures.nth(i).bounding_box() for i in range(n)];grid=page.locator('#grid').bounding_box();assert abs((bounds[-1]['x']+bounds[-1]['width']/2)-(grid['x']+grid['width']/2))<=3,'Odd final group image must be centered'
      assert abs(bounds[0]['y']-bounds[1]['y'])<=3 and bounds[0]['x']+bounds[0]['width']<=bounds[1]['x']+3,'Two columns required'
      for i,color in enumerate([(220,35,20),(20,190,55),(225,170,15)]):
       img=page.locator('#grid figure').filter(has_text='Three color cards').nth(i).locator('img');assert img.evaluate('(x)=>x.complete && x.naturalWidth===96');im=Image.open(io.BytesIO(img.screenshot())).convert('RGB');w,h=im.size;assert max(abs(a-b) for a,b in zip(im.getpixel((int(w*.2),int(h*.4))),color))<40
      evidence['grid_bounds']=bounds
      if Path(os.environ.get('SWECLAR_LOG_DIR','/private/results')).is_dir():page.screenshot(path=str(Path(os.environ.get('SWECLAR_LOG_DIR','/private/results'))/'photo-chat.png'),full_page=True)
     check(5,contacts_grid)
    finally:browser.close()
   if Path(os.environ.get('SWECLAR_LOG_DIR','/private/results')).is_dir():(Path(os.environ.get('SWECLAR_LOG_DIR','/private/results'))/'photo-observations.json').write_text(json.dumps(evidence,indent=2))
   return {'harness_ok':True,'results':[{'ru_id':f'RU-{i:03}',**results[i]} for i in range(1,6)]}
  finally:
   if server and server.poll() is None:server.terminate();server.wait(timeout=10)
if __name__=='__main__':
 try:print(json.dumps(run()))
 except Exception as e:traceback.print_exc();print(json.dumps({'harness_ok':True,'results':[{'ru_id':f'RU-{i:03}','passed':False,'detail':str(e)} for i in range(1,6)]}))
