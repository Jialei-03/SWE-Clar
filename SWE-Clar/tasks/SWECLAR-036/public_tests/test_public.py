"""Public smoke for the supplied HTTP/TLS scaffolding and prepared database."""
import json,os,socket,ssl,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path.cwd()
with socket.socket() as available:available.bind(('127.0.0.1',0));port=available.getsockname()[1]
ctx=ssl.create_default_context(cafile=str(root/'runtime/ca.pem'))
with tempfile.TemporaryFile(mode='w+t') as log:
 process=subprocess.Popen([sys.executable,str(root/'start.py')],cwd=root,env={**os.environ,'API_PORT':str(port)},stdout=log,stderr=subprocess.STDOUT)
 try:
  deadline=time.monotonic()+30
  while True:
   if process.poll() is not None:
    log.seek(0);detail=log.read()[-3000:]
    config=json.loads((root/'runtime/connection.json').read_text())
    for key in ('MARIADB_CONNECTION','SERVER_PFX_PASSWORD'):detail=detail.replace(config[key],'[redacted]')
    raise AssertionError('API exited: '+detail)
   try:
    with urllib.request.urlopen(f'https://127.0.0.1:{port}/health',context=ctx,timeout=2) as response:
     assert response.status==200;health=json.load(response)
    break
   except (OSError,ValueError):
    if time.monotonic()>deadline:raise AssertionError('API did not become ready')
    time.sleep(.1)
  assert health['database_connected'] is True
  assert health['tls_configured'] is True
  assert isinstance(health['migration_count'],int)
  print(json.dumps({'passed':True,'https_request':True,'database_connected':True,'public_baseline_only':True}))
 finally:
  process.terminate()
  try:process.wait(timeout=5)
  except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
