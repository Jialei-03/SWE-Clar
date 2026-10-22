"""Candidate-independent toolchain health, executed before budget."""
import json,subprocess,sys
subprocess.run([sys.executable,'-I','-c',"import json,decimal;assert json.loads('{\"v\":1}')['v']==1;assert decimal.Decimal('0.1')+decimal.Decimal('0.2')==decimal.Decimal('0.3')"],user=1000,group=1000,extra_groups=[],check=True)
print(json.dumps({'passed':True,'prepared_before_budget':True}))
