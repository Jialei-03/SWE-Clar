"""Public ordinary-user build/HTTP/SQLite observer; no business expectations."""
from pathlib import Path
import concurrent.futures,json,os,shutil,socket,sqlite3,subprocess,sys,tempfile,time,urllib.request,urllib.error
r=json.load(sys.stdin)
env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','DOTNET_ROOT':'/opt/dotnet','DOTNET_CLI_TELEMETRY_OPTOUT':'1','DOTNET_NOLOGO':'1','DOTNET_GENERATE_ASPNET_CERTIFICATE':'false','NUGET_PACKAGES':'/opt/sweclar/nuget-cache'}
with tempfile.TemporaryDirectory(prefix='api-observer-') as d:
 d=Path(d);src=d/'source';app=d/'app';db=d/'state.sqlite';shutil.copytree(r['project'],src,ignore=shutil.ignore_patterns('.git','obj','bin','.build','.dotnet-home','__pycache__'))
 for cmd in [['dotnet','restore',str(src/'TransactionsApi.csproj'),'--configfile','/opt/sweclar/NuGet.Config'],['dotnet','publish',str(src/'TransactionsApi.csproj'),'--no-restore','-p:UseSharedCompilation=false','-o',str(app)]]:
  c=subprocess.run(cmd,cwd=src,env=env,capture_output=True,text=True,timeout=60)
  if c.returncode:print(json.dumps({'compile_error':(c.stdout+c.stderr)[-2000:]}));sys.exit(0)
 process=None;log=tempfile.TemporaryFile();base=''
 def request(op):
  payload=op.get('body');raw=op.get('raw')
  headers={'Content-Type':'application/json',**op.get('headers',{})}
  data=raw.encode() if raw is not None else json.dumps(payload).encode() if payload is not None else None
  q=urllib.request.Request(base+op['path'],method=op.get('method','GET'),headers=headers,data=data)
  try:reply=urllib.request.urlopen(q,timeout=6)
  except urllib.error.HTTPError as e:reply=e
  with reply:
   raw=reply.read().decode();
   try:body=json.loads(raw)
   except ValueError:body=None
   return {'status':reply.status,'body':body,'raw':raw}
 def stop():
  global process
  if process is not None:
   process.terminate()
   try:process.wait(timeout=4)
   except subprocess.TimeoutExpired:process.kill();process.wait()
   process=None
 def start(types):
  global process,base
  with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
  base='http://127.0.0.1:'+str(port)
  process=subprocess.Popen(['dotnet',str(app/'TransactionsApi.dll'),'--urls',base],cwd=app,env={**env,'TRANSACTIONS_DB':str(db),'AUTO_REMOVE_NOTE_TYPES':types},stdout=log,stderr=log)
  for _ in range(200):
   if process.poll() is not None:log.seek(0);raise RuntimeError(log.read().decode()[-1200:])
   try:request({'path':'/health'});return
   except (OSError,ValueError):time.sleep(.05)
  raise RuntimeError('HTTP startup timeout')
 rows=[]
 try:
  start(r.get('types',''))
  for op in r.get('operations',[]):
   kind=op.get('op','request')
   if kind=='request':value=request(op)
   elif kind=='parallel':
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:value=list(pool.map(request,op['requests']))
   elif kind=='restart':stop();start(op.get('types',r.get('types','')));value={'restarted':True}
   elif kind=='sql':
    with sqlite3.connect(db) as conn:
     cursor=conn.execute(op['sql'],op.get('params',[]));value={'rows':cursor.fetchall()};conn.commit()
   elif kind=='database':value={'exists':db.is_file(),'sqlite':db.read_bytes().startswith(b'SQLite format 3') if db.exists() else False}
   else:raise ValueError('Unknown observer operation')
   rows.append(value)
  print(json.dumps({'observations':rows}))
 finally:stop();log.close()
