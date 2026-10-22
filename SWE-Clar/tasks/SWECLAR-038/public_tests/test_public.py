"""Visible transport smoke checks; no hidden ranking or policy answers."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/workspace')
spec = importlib.util.spec_from_file_location('public_request_io', root / 'request_io.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
example = json.loads((root / 'example.json').read_text())
assert module.read_request(root / 'example.json') == example
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / 'invalid.json'
    path.write_text('{}')
    try:
        module.read_request(path)
    except ValueError:
        pass
    else:
        raise AssertionError('Request reader accepted missing envelope fields')
for args, stdin in [([str(root / 'example.json')], None), ([], json.dumps(example))]:
    result = subprocess.run([sys.executable, str(root / 'cli.py'), *args],
        input=stdin, capture_output=True, text=True, check=True, timeout=45, cwd=root)
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    assert isinstance(value.get('lineups'), list)
    assert type(value.get('considered')) is int
    assert isinstance(value.get('unused_player_ids'), list)
print(json.dumps({'passed': True, 'request_reader': True, 'file_and_stdin_cli': True,
                  'optimizer_correctness': 'not established by this public smoke check'}))
