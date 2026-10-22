import json,subprocess,sys
code="""from pathlib import Path
import json,secrets
p=Path('/workspace/runtime');p.mkdir(exist_ok=True)
c={'tokens':{'local-alice':'alice','local-bob':'bob'},'users':{'alice':{'follows':['bob']},'bob':{'follows':[]}},'venues':{'demo':{'name':'Synthetic cafe','address':'Example square','latitude':0.001,'longitude':0.002}}}
(p/'config.json').write_text(json.dumps(c))
"""
subprocess.run([sys.executable,'-I','-c',code],check=True,user=1000,group=1000,extra_groups=[],env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1'})
print(json.dumps({'passed':True,'prepared_config':'runtime/config.json','candidate_code_loaded':False}))
