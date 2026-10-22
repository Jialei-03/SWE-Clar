"""Owned WordPress/MariaDB processes in one container; submitted PHP is UID1000."""
from pathlib import Path
import os,json,secrets,shutil,socket,subprocess,tempfile,time,urllib.request,urllib.error,base64
from database_fixture import DatabaseFixture

def identity():return {'user':1000,'group':1000,'extra_groups':[]} if os.geteuid()==0 else {}
class WordPress:
 def __init__(self,project=None,port=0):
  self.process=None;self.database=None;self.directory=None;self.version=0
  try:
   self.database=DatabaseFixture().__enter__();self.directory=tempfile.TemporaryDirectory(prefix='wordpress-');self.root=Path(self.directory.name);self.root.chmod(0o777);self.wp=self.root/'site';shutil.copytree('/opt/sweclar/wordpress',self.wp)
   if project:(self.wp/'wp-content/plugins/synthetic-directory').symlink_to(Path(project).resolve(),target_is_directory=True)
   if not port:
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
   self.port=port;self.url='http://127.0.0.1:'+str(port);self.password=secrets.token_hex(20)
   config={'DB_NAME':self.database.database,'DB_USER':self.database.username,'DB_PASSWORD':self.database.password,'DB_HOST':'127.0.0.1:'+str(self.database.port),'DB_CHARSET':'utf8mb4','DB_COLLATE':'','WP_HOME':self.url,'WP_SITEURL':self.url}
   config.update({k:secrets.token_hex(32) for k in ['AUTH_KEY','SECURE_AUTH_KEY','LOGGED_IN_KEY','NONCE_KEY','AUTH_SALT','SECURE_AUTH_SALT','LOGGED_IN_SALT','NONCE_SALT']})
   text='<?php\n'+''.join('define('+repr(k)+','+repr(v)+');\n' for k,v in config.items())+"define('WP_HTTP_BLOCK_EXTERNAL',true);define('DISABLE_WP_CRON',true);define('AUTOMATIC_UPDATER_DISABLED',true);define('DISALLOW_FILE_MODS',true);$table_prefix='wp_';if(!defined('ABSPATH'))define('ABSPATH',__DIR__.'/');require_once ABSPATH.'wp-settings.php';"
   (self.wp/'wp-config.php').write_text(text)
   self.proof=self.root/'php-process.jsonl';self.proof.touch();self.proof.chmod(0o666)
   code="define('WP_INSTALLING',true);require "+repr(str(self.wp/'wp-load.php'))+";require_once ABSPATH.'wp-admin/includes/upgrade.php';add_filter('pre_wp_mail',fn()=>true);wp_install('Synthetic directory','example-admin','example@example.test',false,'',"+repr(self.password)+");"
   if project:code+="update_option('active_plugins',['synthetic-directory/directory.php']);"
   code+="wp_insert_user(['user_login'=>'example-editor','user_pass'=>'synthetic-unused-password','user_email'=>'editor@example.test','display_name'=>'Example Editor','role'=>'editor']);echo $wp_version;"
   assert self.run_php(code).strip()=='6.8.3'
   self.log=open(self.root/'http.log','w+');self.process=subprocess.Popen(['php','-S','127.0.0.1:'+str(port),'-t',str(self.wp)],stdout=self.log,stderr=self.log,env={'PATH':os.environ['PATH'],'HOME':'/tmp'},**identity())
   status=dict(x.split(':',1) for x in Path(f'/proc/{self.process.pid}/status').read_text().splitlines() if ':' in x);assert set(status['Uid'].split())=={'1000'} and int(status['CapEff'],16)==0
   self.server_proof={'pid':self.process.pid,'uid':1000,'cap_eff':0,'environment_keys':['HOME','PATH'],'parent_sentinel_absent':True,'live_pid_verified':True}
   end=time.monotonic()+10
   while True:
    try:self.get('/?directory_page=about' if project else '/');break
    except Exception:
     if time.monotonic()>end:raise RuntimeError('WordPress HTTP unavailable')
     time.sleep(.05)
   if project:self.reset()
  except BaseException:self.close();raise
 def run_php(self,code):
  prefix="$s=file_get_contents('/proc/self/status');if(!preg_match('/Uid:\\s+1000\\s+1000\\s+1000\\s+1000/',$s)||!preg_match('/CapEff:\\s+0+\\n/',$s)){throw new Exception('PHP identity boundary');}file_put_contents("+repr(str(self.proof))+",json_encode(['pid'=>getmypid(),'uid'=>1000,'cap_eff'=>0]).\"\\n\",FILE_APPEND);"
  r=subprocess.run(['php'],input='<?php '+prefix+code,capture_output=True,text=True,timeout=30,env={'PATH':os.environ['PATH'],'HOME':'/tmp'},**identity());assert r.returncode==0,(r.stderr+r.stdout).replace(self.password,'[runtime credential]')[-1500:];return r.stdout
 def php(self,code):return self.run_php("$_SERVER['HTTP_HOST']="+repr('127.0.0.1:'+str(self.port))+";require "+repr(str(self.wp/'wp-load.php'))+';'+code)
 def option(self,key,value):return self.php('update_option('+repr(key)+',json_decode(base64_decode('+repr(base64.b64encode(json.dumps(value).encode()).decode())+'),true),false);')
 def reset(self,members=None):
  self.version+=1;self.option('directory_content_version',self.version);self.option('directory_render_count',0);self.option('directory_members',members if members is not None else [{'id':'member-a','name':'Example Alpha','group_code':0,'activity_count':0},{'id':'member-b','name':'Example Beta','group_code':3,'activity_count':None},{'id':'member-c','name':'Example Gamma','group_code':10}])
 def get(self,path='/?directory_page=members',cookie=None):
  try:
   request=urllib.request.Request(self.url+path,headers={'Cookie':cookie} if cookie else {})
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=10) as response:return response.status,response.read(),dict(response.headers)
  except urllib.error.HTTPError as error:return error.code,error.read(),dict(error.headers)
 def logged_cookie(self):return self.php("$u=get_user_by('login','example-editor');echo LOGGED_IN_COOKIE.'='.wp_generate_auth_cookie($u->ID,time()+3600,'logged_in');").strip()
 def detach(self):
  self.directory._finalizer.detach();self.database.directory._finalizer.detach()
 def close(self):
  if self.process:
   self.process.terminate()
   try:self.process.wait(timeout=5)
   except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
  if hasattr(self,'log'):self.log.close()
  if self.database:self.database.__exit__(None,None,None)
  if self.directory:self.directory.cleanup()
