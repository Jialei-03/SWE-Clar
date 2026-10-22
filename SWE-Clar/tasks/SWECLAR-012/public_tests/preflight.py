"""Protected, candidate-independent Flutter/HTTP/SQLite integration preflight."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent


def preflight():
    if os.geteuid() != 0:
        raise RuntimeError('Benchmark manager must run independent preflight before the candidate budget')
    root = Path(tempfile.mkdtemp(prefix='sweclar-clinic-preflight-'))
    root.chmod(0o755)
    server = None
    commands = []
    evidence = {}
    try:
        shutil.copytree('/opt/sweclar/flutter-fixture', root / 'project')
        shutil.copy(HERE / 'environment_fixture/environment_test.dart', root / 'project/test/http_sqlite_test.dart')
        (root / 'home').mkdir()
        for path in [root, *root.rglob('*')]:
            os.chown(path, 1000, 1000)
        environment = {'PATH': os.environ['PATH'], 'HOME': str(root / 'home'), 'CI': 'true',
                       'FLUTTER_SUPPRESS_ANALYTICS': 'true'}

        def run(command, extra=None):
            result = subprocess.run(command, cwd=root / 'project', env={**environment, **(extra or {})},
                                    user=1000, group=1000, extra_groups=[], capture_output=True, text=True, timeout=60)
            commands.append({'command': command, 'returncode': result.returncode})
            if result.returncode:
                raise RuntimeError('Prepared Flutter/HTTP environment failed: ' + (result.stdout + result.stderr)[-4000:])

        run(['flutter', 'pub', 'get', '--offline', '--enforce-lockfile'])
        for mode in ('write', 'read'):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            server = subprocess.Popen([sys.executable, str(HERE / 'environment_fixture/service.py'),
                                       '--db', str(root / 'store.sqlite'), '--port', str(port)],
                                      env=environment, user=1000, group=1000, extra_groups=[],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            origin = f'http://127.0.0.1:{port}'
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Independent service fixture failed: ' + server.communicate()[1])
                try:
                    with urllib.request.urlopen(origin + '/notes', timeout=1) as response:
                        assert response.status == 200
                    break
                except OSError:
                    time.sleep(.05)
            else:
                raise RuntimeError('Independent service fixture did not become healthy')
            run(['flutter', 'test', '--no-pub', '--reporter', 'expanded', 'test/http_sqlite_test.dart'],
                {'PROBE_MODE': mode, 'PROBE_ORIGIN': origin})
            server.terminate()
            _, stderr = server.communicate(timeout=10)
            if stderr:
                raise RuntimeError('Independent service fixture error: ' + stderr)
            with sqlite3.connect(f'file:{root}/store.sqlite?mode=ro', uri=True) as database:
                assert database.execute('SELECT id,body FROM notes ORDER BY id').fetchall() == [(1, 'Synthetic clinic fixture')]
                assert database.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            png = (root / f'project/{mode}.png').read_bytes()
            assert png[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', png[16:24]) == (360, 720)
            assert len(png) > 1000
            evidence[mode] = {'png_sha256': hashlib.sha256(png).hexdigest(), 'sqlite_roundtrip': True}
        run([sys.executable, '-I', '-c',
             'import os;assert os.getuid()==1000;assert not os.access("/private",os.R_OK);'
             'assert not os.access("/opt/flutter/bin/cache/flutter_tools.snapshot",os.W_OK);'
             'assert next(x for x in open("/proc/self/status") if x.startswith("CapEff:")).split()[1]=="0000000000000000"'])
        return {'passed': True, 'independent_of_candidate': True, 'candidate_uid': 1000,
                'real_flutter_http_sqlite': evidence, 'fresh_client_and_backend_restart': True,
                'commands': commands}
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            server.communicate(timeout=10)
        subprocess.run([sys.executable, '-I', '-c', 'import shutil,sys;shutil.rmtree(sys.argv[1])', str(root)],
                       user=1000, group=1000, extra_groups=[], check=True)


def prepare_workspace():
    """Resolve the baseline's locked dependencies before any coding budget starts."""
    if os.geteuid() != 0:
        raise RuntimeError('Workspace preparation belongs to the benchmark manager')
    workspace = Path('/workspace')
    home = Path('/tmp/sweclar-home')
    if home.is_symlink():
        raise RuntimeError('Prepared HOME cannot be a symlink')
    home.mkdir(mode=0o755, exist_ok=True)
    # General browser preflight can create cache directories as the manager.
    # Transfer those harmless local caches before the unprivileged Flutter setup;
    # never follow symlinks into the protected SDK/package source directories.
    owned_paths = [home, *home.rglob('*')]
    for path in sorted(owned_paths, key=lambda p: len(p.parts), reverse=True):
        os.chown(path, 1000, 1000, follow_symlinks=False)
    result = subprocess.run(['flutter', 'pub', 'get', '--offline', '--enforce-lockfile'], cwd=workspace,
                            env={'PATH':os.environ['PATH'],'HOME':str(home),'CI':'true'},
                            user=1000, group=1000, extra_groups=[], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Baseline offline dependency preparation failed: '+(result.stdout+result.stderr)[-3000:])
    return {'passed':True,'home':str(home),'command':['flutter','pub','get','--offline','--enforce-lockfile'],
            'before_candidate_budget':True}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-workspace',action='store_true')
    args=parser.parse_args()
    result=preflight()
    if args.prepare_workspace:
        result['workspace_setup']=prepare_workspace()
    print(json.dumps(result))
