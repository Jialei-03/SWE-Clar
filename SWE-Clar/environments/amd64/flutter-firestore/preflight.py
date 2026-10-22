"""Protected environment proof and pre-budget development-service startup."""
import json,os,pathlib,runpy,shutil,subprocess,sys,tempfile
S=runpy.run_path('/opt/sweclar/firestore_service.py')


def preflight():
    base=runpy.run_path('/opt/sweclar/flutter_preflight.py')['preflight']()
    root=pathlib.Path(tempfile.mkdtemp(prefix='sweclar-firestore-preflight-'));os.chmod(root,0o755)
    try:
        shutil.copytree('/opt/sweclar/firestore-fixture',root/'project')
        (root/'dart-home').mkdir()
        if os.geteuid()==0:
            for p in [root/'project',*(root/'project').rglob('*'),root/'dart-home']:os.chown(p,1000,1000)
        with S['session'](root/'server') as origin:
            doc=S['DOCUMENTS']
            S['seed'](origin,{'probe/first':{'note':{'stringValue':'kept'},'relation':{'stringValue':'old'}},'probe/second':{'note':{'stringValue':'untouched'}}})
            code,first=S['request'](origin,'GET',doc+'/probe/first');assert code==200
            write={'update':{'name':first['name'],'fields':{'relation':{'stringValue':'new'}}},'updateMask':{'fieldPaths':['relation']},'currentDocument':{'updateTime':first['updateTime']}}
            assert S['request'](origin,'POST',doc+':commit',{'writes':[write]})[0]==200
            assert S['request'](origin,'GET',doc+'/probe/first')[1]['fields']=={'note':{'stringValue':'kept'},'relation':{'stringValue':'new'}}
            # A stale source precondition must reject the whole real commit.
            second=S['request'](origin,'GET',doc+'/probe/second')[1]
            second_write={'update':{'name':second['name'],'fields':{'note':{'stringValue':'bad'}}},'currentDocument':{'updateTime':second['updateTime']}}
            assert S['request'](origin,'POST',doc+':commit',{'writes':[second_write,write]})[0]!=200
            assert S['request'](origin,'GET',doc+'/probe/second')[1]['fields']['note']['stringValue']=='untouched'
            options={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
            env={'PATH':os.environ['PATH'],'HOME':str(root/'dart-home'),'CI':'true'}
            for command in [['dart','pub','get','--offline','--enforce-lockfile'],['dart','run','probe.dart',origin+doc]]:
                result=subprocess.run(command,cwd=root/'project',env=env,capture_output=True,text=True,timeout=45,**options)
                if result.returncode:raise RuntimeError('Prepared Dart/Firestore probe failed: '+result.stdout+result.stderr)
            assert S['request'](origin,'GET',doc+'/probe/dart-write')[1]['fields']['from_dart']['booleanValue'] is True
        # Each new container receives its own service and generic public example records.
        # Retain an existing development database on repeated health checks in that container.
        state=pathlib.Path('/private/firestore-development.json')
        if state.exists():
            data=json.loads(state.read_text());os.kill(data['pid'],0)
            assert S['request'](data['origin'],'GET',S['DOCUMENTS']+'/clinics')[0]==200
        else:
            service_root=pathlib.Path('/tmp/sweclar-firestore-development')
            process,origin,log=S['start'](service_root,8080)
            try:
                S['seed'](origin,json.loads(pathlib.Path('/opt/sweclar/development_seed.json').read_text()))
                state.write_text(json.dumps({'pid':process.pid,'origin':origin}));state.chmod(0o600)
            except BaseException:S['stop'](process,log);raise
            log.close() # The server has its own descriptor and lives until container teardown.
        return {**base,'passed':True,'firestore_emulator':'1.19.8','java':'21.0.12.1','actual_rest_and_dart_roundtrip':True,'field_mask_preservation':True,'atomic_precondition_rejection':True,'development_service':'http://127.0.0.1:8080','development_service_prestarted':True}
    finally:
        # Service creates user-private temporary paths; remove those as their owner first.
        for name in ['server/home','project','dart-home']:
            p=root/name
            if p.exists():
                # Parent belongs to the manager; grant only deletion access for owned probe data.
                os.chmod(p.parent,0o777)
                options={'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
                subprocess.run([sys.executable,'-I','-c','import shutil,sys;shutil.rmtree(sys.argv[1])',str(p)],check=True,**options)
        shutil.rmtree(root)


if __name__=='__main__':print(json.dumps(preflight()))
