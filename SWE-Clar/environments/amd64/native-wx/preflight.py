import os,sys,json,subprocess,tempfile,shlex
from pathlib import Path
sys.path.insert(0,'/opt/sweclar');from native_preflight import preflight
base=preflight()
with tempfile.TemporaryDirectory(prefix='gui-health-') as temp:
 root=Path(temp);root.chmod(0o777);identity={'user':1000,'group':1000,'extra_groups':[]};env={'PATH':os.environ['PATH'],'HOME':'/tmp','LANG':'C.UTF-8'}
 flags=shlex.split(subprocess.check_output(['wx-config','--cxxflags'],text=True));libs=shlex.split(subprocess.check_output(['wx-config','--libs','std,aui'],text=True))
 subprocess.run(['c++','-std=c++11','-pedantic-errors',*flags,'/opt/sweclar/gui_health.cpp','-o',str(root/'gui'),*libs],check=True,capture_output=True,text=True,env=env,timeout=60,**identity)
 result=subprocess.run(['xvfb-run','-a',str(root/'gui')],check=True,capture_output=True,text=True,env=env,timeout=20,**identity);assert result.stdout.strip()=='native-gui-ready'
base.update(wxwidgets=subprocess.check_output(['wx-config','--version'],text=True).strip(),cmake=subprocess.check_output(['cmake','--version'],text=True).splitlines()[0],actual_gui=True,gui_uid=1000,language='Linux C++11; not a VS2013 check');print(json.dumps(base))
