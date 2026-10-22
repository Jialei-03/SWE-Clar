"""Benchmark-owned temporary MariaDB, with a database-scoped candidate account."""
from pathlib import Path
import os,secrets,socket,subprocess,tempfile,time
import pymysql

class DatabaseFixture:
    def __enter__(self):
        if os.geteuid()!=0:raise RuntimeError('Database provisioning requires benchmark management identity')
        self.directory=tempfile.TemporaryDirectory(prefix='sweclar-db-')
        self.root=Path(self.directory.name);self.root.chmod(0o700)
        self.log=(self.root/'server.log').open('w+')
        self.process=None
        try:
            init=subprocess.run(['mariadb-install-db','--no-defaults','--basedir=/usr','--datadir='+str(self.root/'data'),'--auth-root-authentication-method=normal','--skip-test-db','--user=root'],stdout=self.log,stderr=subprocess.STDOUT,timeout=30)
            if init.returncode:raise RuntimeError('Database initialization failed; inspect protected fixture log')
            with socket.socket() as port:port.bind(('127.0.0.1',0));self.port=port.getsockname()[1]
            self.socket=str(self.root/'db.sock')
            self.process=subprocess.Popen(['mariadbd','--no-defaults','--user=root','--datadir='+str(self.root/'data'),'--socket='+self.socket,'--pid-file='+str(self.root/'server.pid'),'--port='+str(self.port),'--bind-address=127.0.0.1','--skip-log-bin','--innodb-buffer-pool-size=32M','--innodb-use-native-aio=0','--max-connections=20'],stdout=self.log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+20
            while True:
                try:
                    self.admin=pymysql.connect(unix_socket=self.socket,user='root',autocommit=True,connect_timeout=1);break
                except pymysql.MySQLError:
                    if self.process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Database failed to become ready; inspect protected log')
                    time.sleep(.1)
            self.admin_password=secrets.token_hex(24)
            self.database='task_'+secrets.token_hex(8);self.username='candidate_'+secrets.token_hex(6);self.password=secrets.token_hex(24)
            with self.admin.cursor() as cursor:
                cursor.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY %s",(self.admin_password,))
                cursor.execute('CREATE DATABASE `'+self.database+'`')
                cursor.execute("CREATE USER %s@'127.0.0.1' IDENTIFIED BY %s",(self.username,self.password))
                cursor.execute("GRANT ALL PRIVILEGES ON `"+self.database+"`.* TO %s@'127.0.0.1'",(self.username,))
            self.connection_string=f'Server=127.0.0.1;Port={self.port};User ID={self.username};Password={self.password};Database={self.database};Connection Timeout=2;SslMode=Disabled'
            return self
        except Exception:
            self.__exit__(None,None,None);raise

    def candidate_connection(self):
        return pymysql.connect(host='127.0.0.1',port=self.port,user=self.username,password=self.password,database=self.database,autocommit=True,connect_timeout=2)

    def __exit__(self,*args):
        if getattr(self,'admin',None):self.admin.close()
        if self.process:
            self.process.terminate()
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        self.log.close();self.directory.cleanup()
