"""Protected observer; all candidate imports/calls occur under UID1000."""
from pathlib import Path
import json,os,subprocess,sys
class CandidateFailure(Exception):pass

def invoke(operation,**values):
 if os.geteuid()!=0:raise RuntimeError('Benchmark management identity required')
 root=Path(os.environ['SWECLAR_PROJECT_DIR'])
 r=subprocess.run([sys.executable,'-I','/public_tests/invoke.py'],input=json.dumps({'project':str(root),'operation':operation,**values}),text=True,capture_output=True,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'},timeout=45)
 if r.returncode:raise CandidateFailure('Candidate process failed')
 value=json.loads(r.stdout)
 if 'error' in value:raise CandidateFailure(value['error'])
 if operation=='policy':assert value['after_frames']==values['frames'],'Policy mutated caller input'
 return value['result']

def policy(frames,**options):return invoke('policy',frames=frames,options=options)
def observations(video,line_x):return invoke('observations',video=str(video),line_x=line_x)
def pipeline(**arguments):return invoke('pipeline',arguments=arguments)
