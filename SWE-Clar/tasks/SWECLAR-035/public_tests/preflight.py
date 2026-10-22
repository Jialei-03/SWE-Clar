"""Independent capability probe; no candidate imports."""
import copy,json,subprocess,sys
value={"nested":[{"amount":17}]};duplicate=copy.deepcopy(value);duplicate["nested"][0]["amount"]=23
assert value["nested"][0]["amount"]==17
p=subprocess.run([sys.executable,"-I","-c","import json,sys; print(json.dumps(json.load(sys.stdin)))"],input=json.dumps(value),text=True,capture_output=True,timeout=5)
assert p.returncode==0 and json.loads(p.stdout)==value
print(json.dumps({"passed":True,"capabilities":["Python JSON subprocess","independent deep copy"],"external_services":False}))
