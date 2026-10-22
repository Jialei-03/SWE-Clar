"""Visible build/model/browser regressions only."""
import json,os,subprocess,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ui_support import Application,identity
class PublicComponent(unittest.TestCase):
 def test_model_and_actual_navigation(self):
  with Application() as app:
   script="""const assert=require('assert');const {transition}=require(process.argv[1]);const state={route:'home',openNow:false,nested:{value:2}},event={type:'navigate',route:'saved'},config={routes:['home','saved','profile'],protectedRoutes:['profile'],authenticated:false};const before=JSON.stringify([state,event,config]);const result=transition(state,event,config);assert.equal(result.route,'saved');assert.notStrictEqual(result,state);assert.equal(JSON.stringify([state,event,config]),before);const denied=transition(state,{type:'navigate',route:'profile'},config);assert.equal(denied.route,'home');assert.equal(denied.error,'auth_required');"""
   subprocess.run(['node','-e',script,str(app.dist/'model.cjs')],check=True,capture_output=True,text=True,env=app.environment(),**identity())
   env={**os.environ,'UI_BROWSER_HOME':str(app.project/'runtime'),'UI_BROWSER_WRAPPER':str(Path(__file__).parent/'browser_launch.py')}
   r=subprocess.run(['node',str(Path(__file__).parent/'browser_public.cjs'),app.url],env=env,capture_output=True,text=True,timeout=25)
   self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(json.loads(r.stdout)['passed'])
if __name__=='__main__':unittest.main()
