"""Batch MIDI performance processing with independent atomic result publication."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import wave

import mido

from midi_io import load, save
from performance import transform


RENDERER = '/opt/sweclar/render_midi.py'
_RENDER_TIMEOUT = 90


class _ExistingOutput(Exception):
    """Raised when a result path appears before atomic publication."""


def _lexists(path):
    """Unlike Path.exists(), also regard a dangling symlink as existing."""
    return os.path.lexists(os.fspath(path))


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--articulation', choices=['normal', 'staccato'],
                        default='normal')
    args = parser.parse_args(argv)

    if not 0 <= args.seed <= 4294967295:
        parser.error('seed must be an unsigned 32-bit integer')

    # Resolve only after parsing.  resolve(strict=False) does not create a
    # missing output path, but makes the tree-separation check work for '..'
    # and for symlinks in existing parent paths.
    try:
        input_path = args.input.resolve(strict=False)
        output_path = args.output.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        parser.error(f'could not resolve input/output paths: {error}')

    if not input_path.is_dir():
        parser.error('input must be an existing directory')

    # A dangling output symlink is not a directory.  For an existing path,
    # checking the unresolved spelling as well as the resolved target avoids
    # silently treating it as a creatable directory.
    if _lexists(args.output) and not args.output.is_dir():
        parser.error('output must be a directory')
    if output_path.exists() and not output_path.is_dir():
        parser.error('output must be a directory')

    if (output_path.is_relative_to(input_path)
            or input_path.is_relative_to(output_path)):
        parser.error('input and output directory trees must be separate')

    args.input = input_path
    args.output = output_path
    return args


def _discover(root):
    """Recursively discover regular MIDI files without following symlinks."""
    found = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            # An unreadable subtree contains no usable input for this batch;
            # other subtrees can still be processed.
            continue

        for entry in entries:
            # Check this before is_dir/is_file: both otherwise follow a link by
            # default on some platforms, and linked directories are excluded.
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif (entry.is_file(follow_symlinks=False)
                      and Path(entry.name).suffix.lower() in ('.mid', '.midi')):
                    found.append(Path(entry.path))
            except OSError:
                continue

    return sorted(found, key=lambda path: path.relative_to(root).as_posix())


def _regular_file(path):
    try:
        if path.is_symlink():
            return False
        return stat.S_ISREG(path.stat(follow_symlinks=False).st_mode)
    except OSError:
        return False


def _validate_midi_artifact(path):
    if not _regular_file(path):
        raise ValueError('performance MIDI is not a regular file')
    # Parsing the actual bytes, rather than trusting save(), ensures the file
    # is complete before its containing result directory is made visible.
    mido.MidiFile(str(path))


def _validate_wav_artifact(path):
    if not _regular_file(path):
        raise ValueError('rendered WAV is not a regular file')
    with wave.open(str(path), 'rb') as rendered:
        if (rendered.getnchannels(), rendered.getsampwidth(),
                rendered.getframerate(), rendered.getcomptype()) != (2, 2,
                                                                        44100,
                                                                        'NONE'):
            raise ValueError('renderer did not produce stereo 16-bit 44100 Hz PCM')
        frame_count = rendered.getnframes()
        if frame_count <= 0:
            raise ValueError('renderer produced an empty WAV')
        data = rendered.readframes(frame_count)
        expected = frame_count * rendered.getnchannels() * rendered.getsampwidth()
        if len(data) != expected:
            raise ValueError('rendered WAV is truncated')
        if not any(data):
            raise ValueError('renderer produced a silent WAV')


def _parent_paths_to_create(destination, root):
    """Return missing destination parents, nearest first, for cleanup."""
    paths = []
    current = destination.parent
    while current != root and not _lexists(current):
        paths.append(current)
        current = current.parent
    return paths


def _remove_created_parents(paths):
    # Paths are nearest-first, so removing in this order also removes empty
    # nested directories without touching a pre-existing parent.
    for path in paths:
        try:
            path.rmdir()
        except OSError:
            break


def _render_and_publish(args, relative, song, notes):
    """Render into a private directory and atomically publish both artifacts."""
    destination = args.output / relative
    if _lexists(destination):
        return 'existing_output'

    temporary = None
    created_parents = []
    published = False
    try:
        # Do not create per-input destination parents until both artifacts have
        # passed validation.  A failed input consequently leaves no result
        # directory or partial performance/render files.
        args.output.mkdir(parents=True, exist_ok=True)
        if not args.output.is_dir():
            raise OSError('output is not a directory')

        temporary = Path(tempfile.mkdtemp(prefix='.clarswe-', dir=str(args.output)))
        performance_path = temporary / 'performance.mid'
        render_path = temporary / 'render.wav'

        save(song, notes, performance_path)
        _validate_midi_artifact(performance_path)

        subprocess.run(
            [sys.executable, '-I', RENDERER,
             str(performance_path), str(render_path)],
            check=True,
            timeout=_RENDER_TIMEOUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _validate_wav_artifact(render_path)

        # A result path can be created by another process between the initial
        # check and this commit.  Never replace it or alter its contents.
        if _lexists(destination):
            raise _ExistingOutput()
        created_parents = _parent_paths_to_create(destination, args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if _lexists(destination):
            raise _ExistingOutput()

        # Both files are already complete inside this directory.  Renaming the
        # directory makes the pair visible together on the same filesystem.
        os.rename(os.fspath(temporary), os.fspath(destination))
        temporary = None
        published = True
        return None
    except _ExistingOutput:
        return 'existing_output'
    except Exception:
        return 'render_failed'
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        if not published:
            _remove_created_parents(created_parents)


def process(args):
    paths = _discover(args.input)
    results = []
    for path in paths:
        relative = path.relative_to(args.input)
        row = {
            'input': relative.as_posix(),
            'status': 'error',
            'error': None,
            'notes': None,
        }
        destination = args.output / relative

        # Existing results take precedence over parsing/rendering and are never
        # touched, including when the corresponding input later turns out to
        # be invalid.
        if _lexists(destination):
            row['error'] = 'existing_output'
            results.append(row)
            continue

        try:
            song = load(path)
            transformed = transform(song, args.seed, args.articulation)
        except Exception:
            row['error'] = 'invalid_midi'
            results.append(row)
            continue

        error = _render_and_publish(args, relative, song, transformed)
        if error is None:
            row.update(status='ok', notes=len(transformed))
        else:
            row['error'] = error
        results.append(row)

    return results


def main():
    results = process(arguments())
    print(json.dumps({'results': results}, separators=(',', ':')))
    return int(any(row['status'] == 'error' for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
