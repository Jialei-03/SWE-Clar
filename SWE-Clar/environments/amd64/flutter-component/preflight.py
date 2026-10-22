"""Protected Flutter capability check; never imports the candidate project."""
import json,os,pathlib,runpy,shutil,struct,subprocess,sys,tempfile,time


def preflight():
    base=runpy.run_path('/opt/sweclar/web_preflight.py')['preflight']()
    root=pathlib.Path(tempfile.mkdtemp(prefix='sweclar-flutter-preflight-'))
    os.chmod(root,0o755)
    try:
        shutil.copytree('/opt/sweclar/flutter-fixture',root/'project')
        (root/'home').mkdir()
        for item in [root,*root.rglob('*')]:os.chown(item,1000,1000)
        env={'PATH':os.environ['PATH'],'HOME':str(root/'home'),'CI':'true','FLUTTER_SUPPRESS_ANALYTICS':'true'}
        commands=[['flutter','--version','--machine'],['flutter','pub','get','--offline','--enforce-lockfile'],['flutter','test','--no-pub','--reporter','expanded','test/environment_test.dart']]
        evidence=[]
        for command in commands:
            start=time.monotonic()
            result=subprocess.run(command,cwd=root/'project',env=env,user=1000,group=1000,extra_groups=[],capture_output=True,text=True,timeout=60)
            if result.returncode:
                raise RuntimeError('Prepared Flutter capability failed: '+str(command)+'\n'+(result.stdout+result.stderr)[-3000:])
            evidence.append({'command':command,'elapsed_seconds':round(time.monotonic()-start,3)})
            if command==commands[0]:
                version=json.loads(result.stdout)
                assert version['frameworkRevision']=='d3b14c876900e553bc736ca19295fc09e3853e8e'
                assert version['engineRevision']=='a804b261645ef8c13eb3d5c44a5c2fb0340c5539'
                assert version['dartSdkVersion']=='3.13.2'
        assert json.loads((root/'project/state.json').read_text())=={'count':1}
        png=(root/'project/render.png').read_bytes()
        assert png[:8]==b'\x89PNG\r\n\x1a\n' and struct.unpack('>II',png[16:24])==(360,720)
        assert len(png)>1000
        # Use the same unprivileged identity to verify that SDK sources stay protected.
        result=subprocess.run([sys.executable,'-I','-c',
            'import os; assert os.getuid()==1000; assert not os.access("/private",os.R_OK); assert not os.access("/opt/flutter/bin/cache/flutter_tools.snapshot",os.W_OK); assert not os.access("/opt/pub-cache/hosted",os.W_OK)'],
            user=1000,group=1000,extra_groups=[],capture_output=True,text=True,check=True)
        return {**base,'passed':True,'flutter':'3.47.2','dart':'3.13.2','flutter_render':True,'real_fonts':True,'atomic_file_roundtrip':True,'flutter_candidate_uid':1000,'sdk_and_hosted_packages_protected':True,'flutter_commands':evidence}
    finally:
        # Pub metadata may include private user directories; cleanup as their owner.
        subprocess.run([sys.executable,'-I','-c','import shutil,sys; shutil.rmtree(sys.argv[1])',str(root)],user=1000,group=1000,extra_groups=[],check=True)


if __name__=='__main__':print(json.dumps(preflight()))
