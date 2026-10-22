from pathlib import Path
import io,json,os,secrets
from pypdf import PdfReader
from playwright.sync_api import sync_playwright,expect
from transport import WHITE_PATH

def exercise_browser(a,data):
 os.environ['REPORT_PRIVATE_SENTINEL']=secrets.token_hex(24)
 with sync_playwright() as p:
  folder=a.path/'browser';folder.mkdir();folder.chmod(0o777);proof=folder/'identity.json'
  browser=p.chromium.launch(headless=True,executable_path='/public_tests/browser_launcher.py',downloads_path=str(folder),env={'PATH':WHITE_PATH,'HOME':'/tmp','CLARSWE_BROWSER_BINARY':p.chromium.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
  try:
   observed=json.loads(proof.read_text());fields=dict(x.split(':',1) for x in Path('/proc/%s/status'%observed['pid']).read_text().splitlines() if ':' in x)
   assert set(fields['Uid'].split())=={'1000'} and int(fields['CapEff'],16)==0
   assert observed['uid']==1000 and observed['cap_eff']==0 and 'REPORT_PRIVATE_SENTINEL' not in observed['environment_keys']
   for width in [1280,390]:
    page=browser.new_page(viewport={'width':width,'height':844},accept_downloads=True);page.set_default_timeout(7000)
    page.goto(a.url)
    def click(name,path):
     with page.expect_response(lambda r:r.url.endswith(path) and r.request.method=='POST') as response:page.get_by_role('button',name=name,exact=True).click()
     assert 200<=response.value.status<300
     return response.value.json()
    page.get_by_label('Email',exact=True).fill('browser%s@example.test'%width);page.get_by_label('Password',exact=True).fill('synthetic-passphrase');u=click('Create account','/register');click('Start trial','/trial')
    page.get_by_label('Room name',exact=True).fill('Browser room');click('Create room','/rooms')
    expect(page.locator('#room-options option')).to_have_count(1)
    page.get_by_label('Title',exact=True).fill('Browser report');page.get_by_label('Details',exact=True).fill('Original details');click('Create content','/content')
    expect(page.get_by_role('heading',name='Browser report',exact=True)).to_be_visible()
    page.get_by_label('Image file',exact=True).set_input_files({'name':'synthetic.jpg','mimeType':'image/jpeg','buffer':data});click('Upload image','/assets')
    pic=page.locator('#images img');expect(pic).to_have_count(1)
    page.wait_for_function("() => document.querySelector('#images img')?.naturalWidth > 0")
    pixels=pic.evaluate("im=>{let c=document.createElement('canvas');c.width=im.naturalWidth;c.height=im.naturalHeight;let x=c.getContext('2d');x.drawImage(im,0,0);return [c.width,c.height,...x.getImageData(20,15,1,1).data,...x.getImageData(20,45,1,1).data]}")
    assert pixels[:2]==[40,60]
    for actual,want in [(pixels[2:5],[220,30,40]),(pixels[6:9],[30,40,220])]:assert all(abs(x-y)<16 for x,y in zip(actual,want))
    click('Mark complete','/complete');page.get_by_label('Report title',exact=True).fill('Edited report');page.get_by_label('Report details',exact=True).fill('Completed content remains editable');click('Save report','/edit')
    expect(page.get_by_role('heading',name='Edited report',exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='Download printable PDF',exact=True)).to_be_disabled();expect(page.get_by_role('button',name='Create share copy',exact=True)).to_be_disabled()
    payment=a.receipt(u,'browser-paid-%s'%width);page.get_by_label('Local payment receipt',exact=True).fill(payment);click('Activate plan','/activate')
    expect(page.get_by_role('button',name='Download printable PDF',exact=True)).to_be_enabled()
    with page.expect_download() as download:page.get_by_role('button',name='Download printable PDF',exact=True).click()
    text=''.join(x.extract_text() or '' for x in PdfReader(download.value.path()).pages);assert 'Edited report' in text and 'Completed content remains editable' in text
    shared=click('Create share copy','/share');assert shared['title']=='Edited report' and shared['details']=='Completed content remains editable'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
    click('Sign out','/logout');expect(page.get_by_role('button',name='Create account',exact=True)).to_be_visible();a.deny('/me',token=u['token']);page.close()
  finally:browser.close()
