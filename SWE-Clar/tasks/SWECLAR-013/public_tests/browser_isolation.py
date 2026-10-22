"""Protected process boundary for browser execution; contains no business oracle."""
import json,os,secrets,shutil,tempfile
from pathlib import Path

def launch(browser_type, **options):
    root=Path(tempfile.mkdtemp(prefix='browser-boundary-'));root.chmod(0o755)
    downloads=root/'downloads';downloads.mkdir();downloads.chmod(0o777)
    proof=downloads/'process.json'
    # A synthetic private parent value proves the browser receives no inherited environment.
    os.environ['CLARSWE_PRIVATE_BROWSER_SENTINEL']=secrets.token_hex(24)
    options.pop('executable_path',None);options.pop('env',None)
    options.update(executable_path='/public_tests/browser_launcher.py',downloads_path=str(downloads),env={'PATH':os.environ['PATH'],'HOME':str(downloads),'CLARSWE_BROWSER_BINARY':browser_type.executable_path,'CLARSWE_BROWSER_PROOF':str(proof)})
    try:
        browser=browser_type.launch(**options)
        record=json.loads(proof.read_text())
        status=dict(line.split(':',1) for line in Path(f"/proc/{record['pid']}/status").read_text().splitlines() if ':' in line)
        assert set(status['Uid'].split())=={'1000'} and int(status['CapEff'],16)==0
        assert record['uid']==1000 and record['cap_eff']==0 and record['environment_keys']==['HOME','PATH']
        record['live_pid_verified']=True;record['parent_uid']=os.getuid();record['parent_sentinel_present']=True
        if os.getuid()==0:
            with open('/private/results/browser-isolation.jsonl','a') as out:out.write(json.dumps(record)+'\n')
        original_close=browser.close
        def close(*args,**kwargs):
            try:return original_close(*args,**kwargs)
            finally:shutil.rmtree(root,ignore_errors=True)
        browser.close=close
        return browser
    except BaseException:
        shutil.rmtree(root,ignore_errors=True)
        raise
