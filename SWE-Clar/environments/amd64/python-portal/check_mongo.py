import tempfile,subprocess,pathlib,sys
with tempfile.TemporaryDirectory() as td:
 log=pathlib.Path(td)/'mongo.log'
 with log.open('w') as stream:
  p=subprocess.Popen(['mongod','--dbpath',td,'--bind_ip','127.0.0.1','--port','27017','--replSet','health','--wiredTigerCacheSizeGB','0.25','--quiet'],stdout=stream,stderr=stream)
  try:subprocess.run(['node',str(pathlib.Path(__file__).with_name('mongo_health.cjs'))],check=True,timeout=30)
  except Exception:
   print(log.read_text()[-4000:],file=sys.stderr);raise
  finally:p.terminate();p.wait(timeout=10)
