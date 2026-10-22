"""Authenticated per-attempt Mongo fixture. Call only from benchmark management."""
import base64,json,os,secrets,socket,subprocess
from pathlib import Path

class MongoFixture:
    def __init__(self, private_root):
        if os.geteuid()!=0:raise RuntimeError('Database management requires benchmark identity')
        self.root=Path(private_root);self.root.mkdir(mode=0o700,parents=True,exist_ok=True);self.root.chmod(0o700)
        self.data=self.root/'database';self.data.mkdir()
        key=self.root/'replica.key';key.write_bytes(base64.b64encode(secrets.token_bytes(512)));key.chmod(0o600)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        self.host=f'127.0.0.1:{port}';self.log=(self.root/'mongod.log').open('w');self.process=None
        password=secrets.token_hex(24)
        self.admin_uri=f'mongodb://manager:{password}@{self.host}/?authSource=admin&replicaSet=sweclar_fixture'
        try:
            self.process=subprocess.Popen(['mongod','--dbpath',str(self.data),'--bind_ip','127.0.0.1','--port',str(port),'--replSet','sweclar_fixture','--keyFile',str(key),'--auth','--wiredTigerCacheSizeGB','0.25','--quiet'],stdout=self.log,stderr=self.log)
            self.control({'operation':'initialize','uri':f'mongodb://{self.host}/','host':self.host,'password':password})
        except BaseException:self.close();raise
    def control(self,payload):
        result=subprocess.run(['node',str(Path(__file__).with_name('mongo_control.cjs'))],input=json.dumps(payload),text=True,capture_output=True,timeout=35)
        if result.returncode:raise RuntimeError('Benchmark Mongo provisioning failed: '+result.stderr[-300:])
        assert json.loads(result.stdout)['passed']
    def provision(self,database):
        if not database.replace('_','').isalnum():raise ValueError('Invalid database name')
        password=secrets.token_hex(24);self.control({'operation':'provision','uri':self.admin_uri,'database':database,'password':password})
        return f'mongodb://candidate:{password}@{self.host}/{database}?authSource={database}&replicaSet=sweclar_fixture'
    def close(self):
        if self.process and self.process.poll() is None:self.process.terminate();self.process.wait(timeout=15)
        self.log.close()
