"""Benchmark-owned database lifetime; launched before the candidate budget."""
import json,os,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from database_fixture import MongoFixture
private=Path(sys.argv[1]);fixture=MongoFixture(private/'mongo')
def stop(*_):raise SystemExit(0)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
try:
 uri=fixture.provision('portal_development')
 (private/'ready.json').write_text(json.dumps({'MONGODB_URI':uri,'PORTAL_DATABASE':'portal_development'}))
 while True:
  if fixture.process.poll() is not None:raise RuntimeError('Development database stopped')
  time.sleep(1)
finally:fixture.close()
