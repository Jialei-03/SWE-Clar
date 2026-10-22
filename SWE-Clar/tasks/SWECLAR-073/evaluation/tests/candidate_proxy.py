import os,json,subprocess,sys

def run(request):
 root=os.environ['CANDIDATE_ROOT'];p=subprocess.run([sys.executable,'-I','/public_tests/file_worker.py'],input=json.dumps({'project':root,**request}),capture_output=True,text=True,cwd=root,user=1000,group=1000,extra_groups=[],env={'PATH':os.environ['PATH'],'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'},timeout=35)
 assert p.returncode==0,p.stderr[-1200:];output=json.loads(p.stdout)
 for row,op in zip(output['observations'],request['operations']):
  assert row['returncode']==0 and row['value'] is not None,(row['returncode'],row['stderr']);assert 'error' not in row['value'],row['value'];assert isinstance(row['value']['report'],dict)
  if op.get('via')!='cli':assert json.dumps(row['value']['after'],sort_keys=True)==json.dumps([op['assets'],op['taxonomy']],sort_keys=True),'Inputs mutated'
  for name,info in output['before'].items():
   if name.startswith('source/') or name.startswith('outside/'):assert row['files'].get(name)==info,'Source/outside modified'
 return output
