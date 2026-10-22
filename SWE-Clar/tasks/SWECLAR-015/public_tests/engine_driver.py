"""JSON transport for the public Python API, containing no expected answers."""
import contextlib
import importlib
import json
import os
import numbers
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ.get('SWECLAR_PROJECT_DIR', '/workspace')).resolve()))


def main():
    calls = json.load(sys.stdin)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            engine = importlib.import_module('engine')
    except Exception as error:
        print(json.dumps({'load_error': type(error).__name__}))
        return 1
    outputs = []
    for call in calls:
        try:
            if call['method'] not in {'pairs', 'solve', 'transform', 'geometry'}:
                raise ValueError('Unsupported developer method')
            with contextlib.redirect_stdout(sys.stderr):
                value = getattr(engine, call['method'])(*call['args'])
            outputs.append({'value': value})
        except Exception as error:
            outputs.append({'error': 'ValueError' if isinstance(error, ValueError) else type(error).__name__})
    print(json.dumps(outputs, allow_nan=False, default=lambda value: float(value) if isinstance(value, numbers.Number) else (_ for _ in ()).throw(TypeError('Not a numeric JSON value'))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
