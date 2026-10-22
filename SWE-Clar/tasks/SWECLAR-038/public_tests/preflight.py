"""Benchmark-owned interpreter health check, before the candidate budget."""
import json
import subprocess
import sys

r = subprocess.run([sys.executable, '-I', '-c',
    'import json,heapq,itertools,math; assert math.isfinite(1.25); '
    'assert json.loads("[1,2]")==[1,2]; print("stdlib ready")'],
    capture_output=True, text=True, check=True, timeout=10,
    user=1000, group=1000, extra_groups=[])
print(json.dumps({'passed': True, 'ordinary_user_stdlib': r.stdout.strip(),
                  'prepared_before_budget': True}))
