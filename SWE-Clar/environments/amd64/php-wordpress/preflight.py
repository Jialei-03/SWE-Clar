import json,subprocess,sys
sys.path.insert(0,'/opt/sweclar')
from wordpress_fixture import WordPress
base=subprocess.run([sys.executable,'-I','/opt/sweclar/base_preflight.py'],capture_output=True,text=True,check=True)
w=WordPress()
try:
 assert w.php('echo $wp_version;').strip()=='6.8.3';assert w.php('echo get_option("blogname");').strip()=='Synthetic directory';assert w.get('/')[0]==200
 result=json.loads(base.stdout);result['wordpress']={'version':'6.8.3','database':w.php('global $wpdb;echo $wpdb->get_var("SELECT VERSION()");').strip(),'uid':1000,'real_install':True};assert result['passed'];print(json.dumps(result))
finally:w.close()
