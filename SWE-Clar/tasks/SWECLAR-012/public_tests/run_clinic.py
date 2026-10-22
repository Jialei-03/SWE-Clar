"""Observe real clinic UI and HTTP operations from a public session description."""
import argparse
import base64
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clinic_support import run_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit('Choose a new or empty output directory to preserve previous observations')
    result = run_session(json.loads(args.script.read_text()))
    args.output.mkdir(parents=True, exist_ok=True)
    for name, encoded in result.pop('captures_base64').items():
        (args.output / name).write_bytes(base64.b64decode(encoded))
    (args.output / 'observations.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'completed': True, 'output': str(args.output), 'operations': len(result['observations'])}))


if __name__ == '__main__':
    main()
