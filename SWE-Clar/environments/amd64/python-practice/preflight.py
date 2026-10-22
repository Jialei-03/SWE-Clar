"""Protected checks of UI compilation, real media and prepared practice services."""
import base64,json,os,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
sys.path.insert(0,'/opt/sweclar')
from web_preflight import preflight as web_preflight

def main():
    result=web_preflight()
    try:
        with urlopen('http://127.0.0.1:38910/health',timeout=1) as response:ready=json.load(response)
        assert ready=={'ready':True,'fixture':'synthetic-practice'}
    except OSError:
        if os.getuid()!=0:raise RuntimeError('Manager must initialize practice service before candidate work')
        subprocess.Popen([sys.executable,'-I','/opt/sweclar/fixture.py'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        for _ in range(100):
            try:
                with urlopen('http://127.0.0.1:38910/health',timeout=1) as response:ready=json.load(response)
                break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('Prepared receipt service unavailable')
    with urlopen('http://127.0.0.1:38910/receipts/demo-a',timeout=3) as response:receipt=json.load(response)
    assert receipt['payload']['status']=='paid' and len(receipt['signature'])==64
    version=subprocess.check_output(['node','--version'],text=True).strip();assert version=='v22.18.0'
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);root.chmod(0o777)
        script="""const esbuild=require('/opt/sweclar/ui/node_modules/esbuild');esbuild.buildSync({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {Pressable,Text} from 'react-native';createRoot(document.getElementById('root')).render(React.createElement(Pressable,{onPress:()=>document.title='ui-ready'},React.createElement(Text,null,'Check UI')));`,resolveDir:'/opt/sweclar/ui',loader:'js'},bundle:true,absWorkingDir:'/opt/sweclar/ui',nodePaths:['/opt/sweclar/ui/node_modules'],alias:{'react-native':'react-native-web'},outfile:process.argv[1],define:{'process.env.NODE_ENV':'"production"'}});"""
        identity={'user':1000,'group':1000,'extra_groups':[]} if os.getuid()==0 else {}
        compiled=subprocess.run(['node','-e',script,str(root/'app.js')],capture_output=True,text=True,timeout=30,**identity)
        if compiled.returncode:raise RuntimeError('Prepared UI build failed: '+compiled.stderr)
        wav=base64.b64encode(Path('/tmp/sweclar-practice/tone-a.wav').read_bytes()).decode()
        (root/'index.html').write_text('<div id="root"></div><script src="app.js"></script><audio id="audio" src="data:audio/wav;base64,'+wav+'"></audio>')
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required'])
            try:
                page=browser.new_page();page.goto((root/'index.html').as_uri());page.get_by_text('Check UI',exact=True).click();page.wait_for_function("document.title==='ui-ready'")
                page.locator('#audio').evaluate('(a)=>a.play()');page.wait_for_function("document.querySelector('audio').currentTime>.15")
                before=page.locator('#audio').evaluate('(a)=>{a.pause();return a.currentTime}')
                page.wait_for_timeout(200);after=page.locator('#audio').evaluate('(a)=>a.currentTime');assert abs(after-before)<.05
                page.locator('#audio').evaluate('(a)=>a.play()');page.wait_for_function('(x)=>document.querySelector("audio").currentTime>x+.15',arg=after)
            finally:browser.close()
    result.update(node=version,ui_compile_as_candidate=True,react_native_web=True,real_audio_play_pause_resume=True,receipt_service=True)
    print(json.dumps(result))

if __name__=='__main__':main()
