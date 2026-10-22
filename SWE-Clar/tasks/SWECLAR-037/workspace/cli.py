import json,sys
from pipeline import run_pipeline
with open(sys.argv[1]) as f:request=json.load(f)
print(json.dumps(run_pipeline(**request)))
