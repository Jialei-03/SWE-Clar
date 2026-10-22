import json,subprocess,sys
r=subprocess.run([sys.executable,'-I','/public_tests/api_worker.py'],input=json.dumps({'project':'.','operations':[{'path':'/health'},{'path':'/unknown'}]}),capture_output=True,text=True,check=True)
v=json.loads(r.stdout);assert 'compile_error' not in v,v
assert v['observations'][0]['status']==200 and v['observations'][0]['body'].get('ok') is True
assert v['observations'][1]['status']==404 and v['observations'][1]['body'].get('error')=='route_not_found'
print('Offline ASP.NET build and HTTP foundation passed')
