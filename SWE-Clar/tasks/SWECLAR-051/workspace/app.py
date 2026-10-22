"""Batch MIDI performance processing with per-input result publication."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from midi_io import load, save
from performance import transform

RENDERER = '/opt/sweclar/render_midi.py'


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--articulation', choices=['normal', 'staccato'], default='normal')
    args = parser.parse_args()
    args.input, args.output = args.input.resolve(), args.output.resolve()
    if not 0 <= args.seed <= 4294967295:
        parser.error('seed must be an unsigned 32-bit integer')
    if not args.input.is_dir():
        parser.error('input must be a directory')
    if args.output.exists() and not args.output.is_dir():
        parser.error('output must be a directory')
    if args.output.is_relative_to(args.input) or args.input.is_relative_to(args.output):
        parser.error('input and output directories must be separate')
    return args


def process(args):
    paths = sorted((p for p in args.input.glob('*')
                    if not p.is_symlink() and p.is_file() and p.suffix.lower() in ['.mid', '.midi']),
                   key=lambda p: p.relative_to(args.input).as_posix())
    results = []
    for path in paths:
        relative = path.relative_to(args.input)
        destination = args.output / relative
        row = {'input': relative.as_posix(), 'status': 'error', 'error': None, 'notes': None}
        try:
            song = load(path)
            notes = transform(song, args.seed, args.articulation)
        except (OSError, ValueError, EOFError, KeyError, IndexError):
            row['error'] = 'invalid_midi'
            results.append(row)
            break
        try:
            destination.mkdir(parents=True, exist_ok=True)
            save(song, notes, destination/'performance.mid')
            subprocess.run([sys.executable, RENDERER, str(destination/'performance.mid'),
                            str(destination/'render.wav')], check=True, timeout=90,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            row.update(status='ok', notes=len(notes))
        except (OSError, ValueError, subprocess.SubprocessError):
            row['error'] = 'render_failed'
        results.append(row)
        if row['status'] == 'error':
            break
    return results


def main():
    results = process(arguments())
    print(json.dumps({'results': results}, separators=(',', ':')))
    return int(any(row['status'] == 'error' for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
