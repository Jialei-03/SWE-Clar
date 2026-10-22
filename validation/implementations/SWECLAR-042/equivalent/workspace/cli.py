"""Read one synthetic command from stdin and persist its successful result."""
import json
import sys
from ledger import apply_action

if __name__ == '__main__':
    request = json.load(sys.stdin)
    print(json.dumps(apply_action(sys.argv[1], request['seed'], request['action']), allow_nan=False))
