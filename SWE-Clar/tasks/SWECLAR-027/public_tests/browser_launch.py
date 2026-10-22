#!/usr/bin/env python3
"""Protected browser launcher: candidate web content always uses UID 1000."""
import os
from pathlib import Path
import sys

binary = os.environ['ARENA_BROWSER_BINARY']
profile = next((arg.split('=', 1)[1] for arg in sys.argv[1:] if arg.startswith('--user-data-dir=')), None)
if '-profile' in sys.argv:
    profile = sys.argv[sys.argv.index('-profile') + 1]
if os.geteuid() == 0:
    if profile:
        path = Path(profile)
        if path.is_symlink() or not str(path).startswith('/tmp/') or not path.is_dir():
            raise SystemExit('Unexpected browser profile location')
        for child in sorted(path.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            os.chown(child, 1000, 1000, follow_symlinks=False)
        os.chown(path, 1000, 1000)
    os.setgroups([])
    os.setgid(1000)
    os.setuid(1000)
assert os.getuid() == 1000
if profile:
    Path(os.environ['HOME'], 'profile-location.json').write_text(__import__('json').dumps(profile))
status = Path('/proc/self/status').read_text()
assert int(next(line for line in status.splitlines() if line.startswith('CapEff:')).split()[1], 16) == 0
os.execv(binary, [binary, *sys.argv[1:]])
