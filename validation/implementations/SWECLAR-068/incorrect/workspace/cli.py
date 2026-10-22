import json,sys
from solution import evaluate_indicator
value=json.load(sys.stdin);json.dump(evaluate_indicator(value['config'],value['context']),sys.stdout,allow_nan=False);print()
