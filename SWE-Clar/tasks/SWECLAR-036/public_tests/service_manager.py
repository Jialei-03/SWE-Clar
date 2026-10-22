"""Own the development database lifetime outside the candidate account."""
import json,signal,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from database_fixture import DatabaseFixture
from certificates import certificates
private=Path(sys.argv[1])
def stop(*_):raise SystemExit(0)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
with DatabaseFixture() as fixture:
 certdir=private/'certs';certdir.mkdir(mode=0o700)
 password=certificates(certdir)
 (private/'ready.json').write_text(json.dumps({'MARIADB_CONNECTION':fixture.connection_string,'SERVER_PFX_PASSWORD':password}))
 while True:
  if fixture.process.poll() is not None:raise RuntimeError('Prepared database stopped')
  time.sleep(1)
