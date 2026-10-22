"""Validate all 100 registries, private contracts and role projections offline."""
from pathlib import Path
import json,sys
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'harness'))
from harness import validate
from runtime.registry import load_registry
from runtime.delivery_contract import load_delivery_contract,private_project_context
data=root/'SWE-Clar';report=validate(data)
for task in sorted((data/'tasks').iterdir()):
 if not task.is_dir():continue
 registry=load_registry(task);load_delivery_contract(task,registry);private_project_context(task,registry)
assert report['task_count']==100 and report['ru_count']==512
print(json.dumps({'tasks':100,'requirement_units':512,'contracts_and_role_projections':100,'docker_execution_verified':False,'model_requests':0},indent=2))
