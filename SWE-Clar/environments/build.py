"""Build selected or all task images locally; public image hosting is optional."""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(argv):
    subprocess.run(argv, check=True)


def output(argv):
    return subprocess.check_output(argv, text=True).strip()


def plan(task_ids):
    tasks = ROOT / 'tasks'
    selected = task_ids or sorted(p.name for p in tasks.iterdir() if p.is_dir())
    if len(set(selected)) != len(selected):
        raise ValueError('Duplicate task IDs')
    profiles = {}
    for task_id in selected:
        if Path(task_id).name != task_id or not (tasks / task_id).is_dir():
            raise ValueError('Unknown task: ' + task_id)
        profiles[task_id] = json.loads((tasks / task_id / 'environment.json').read_text())['profile']
    from frozen_extensions import profile_order
    return profiles, profile_order(ROOT / 'environments', sorted(set(profiles.values())))


def verify_task(spec):
    command = spec['preflight_command']
    command = ['sh', '-c', command] if isinstance(command, str) else command
    resources = spec['resources']
    run(['docker', 'run', '--rm', '--platform', 'linux/amd64', '--network', 'none',
         '--cpus', str(resources['cpus']), '--memory', resources['memory'],
         '--shm-size', resources['shm_size'], spec['image_ref']] + command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', action='append', help='Repeat to select tasks; default: all 100')
    parser.add_argument('--output', type=Path, required=True, help='Persistent build directory outside the dataset')
    parser.add_argument('--registry', help='Optional existing OCI repository prefix; requires docker login')
    parser.add_argument('--local-registry-port', type=int, default=5500)
    parser.add_argument('--plan', action='store_true', help='Show task/profile coverage without building')
    args = parser.parse_args()
    tasks, profiles = plan(args.task)
    if args.plan:
        print(json.dumps({'task_count': len(tasks), 'profiles': profiles, 'tasks': tasks}, indent=2))
        return
    work = args.output.resolve()
    if work.is_relative_to(ROOT) or ROOT.is_relative_to(work):
        raise ValueError('Output must be outside, and not an ancestor of, the dataset')
    if sys.version_info < (3, 12):
        raise RuntimeError('Python 3.12 or later is required')
    missing = [tool for tool in ['docker', 'npm', 'git', 'dpkg-deb'] if not shutil.which(tool)]
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        raise RuntimeError('Full construction is supported on Linux x86_64; use a Linux x86_64 machine')
    if missing:
        raise RuntimeError('Missing prerequisites: ' + ', '.join(missing))
    info = json.loads(output(['docker', 'info', '--format', '{{json .}}']))
    if info['OSType'] != 'linux' or info['Architecture'] not in ('x86_64', 'amd64'):
        raise RuntimeError('A Linux AMD64 Docker engine is required')
    work.mkdir(parents=True, exist_ok=True)
    repository = args.registry
    if not repository:
        if not 1024 <= args.local_registry_port <= 65535:
            raise ValueError('Invalid local registry port')
        # Dedicated loopback registry gives task images OCI manifest digests without public hosting.
        name = 'swe-clar-registry-' + hashlib.sha256(str(work).encode()).hexdigest()[:12]
        found = output(['docker', 'ps', '-aq', '--filter', 'name=^/' + name + '$'])
        if found:
            container = json.loads(output(['docker', 'inspect', name]))[0]
            assert container['Config']['Labels'].get('swe-clar.build-root') == str(work), 'Registry name owned by another build'
            assert container['HostConfig']['NetworkMode'] == 'host', 'Registry network changed'
            assert 'REGISTRY_HTTP_ADDR=127.0.0.1:' + str(args.local_registry_port) in container['Config']['Env'], 'Registry port changed; use the original port'
            run(['docker', 'start', name])
        else:
            (work / 'registry').mkdir(exist_ok=True)
            run(['docker', 'run', '-d', '--name', name, '--label', 'swe-clar.build-root=' + str(work),
                 '--network', 'host', '-e', f'REGISTRY_HTTP_ADDR=127.0.0.1:{args.local_registry_port}',
                 '-v', str(work / 'registry') + ':/var/lib/registry', 'registry:2'])
        repository = f'127.0.0.1:{args.local_registry_port}/swe-clar'
        (work / 'registry-info.json').write_text(json.dumps({'container': name, 'repository': repository}, indent=2))
    command = [sys.executable, str(ROOT / 'environments/prepare_amd64.py'), '--records', str(work / 'profiles'), '--cache', str(work / 'downloads')]
    for profile in sorted(set(tasks.values())):
        command += ['--profile', profile]
    run(command)
    catalogs = work / 'task-catalogs'
    catalogs.mkdir(exist_ok=True)
    merged = {'tasks': {}}
    for task_id, profile in tasks.items():
        catalog = catalogs / (task_id + '.json')
        fingerprint = hashlib.sha256()
        for base in [ROOT / 'tasks' / task_id, ROOT / 'environments']:
            for source in sorted(base.rglob('*')):
                if source.is_file() and '__pycache__' not in source.parts:
                    fingerprint.update(str(source.relative_to(ROOT)).encode())
                    fingerprint.update(source.read_bytes())
        fingerprint = fingerprint.hexdigest()
        stamp = catalogs / (task_id + '.inputs.sha256')
        if catalog.exists():
            if not stamp.exists() or stamp.read_text().strip() != fingerprint:
                raise RuntimeError('Build inputs changed for ' + task_id + '; use a new output directory')
            existing = json.loads(catalog.read_text())
            ref = existing['tasks'][task_id]['image_ref']
            image = json.loads(output(['docker', 'image', 'inspect', ref]))[0]
            if image['Architecture'] != 'amd64':
                raise RuntimeError('Cached task image architecture mismatch')
            verify_task(existing['tasks'][task_id])
            merged['tasks'].update(existing['tasks'])
            continue
        run([sys.executable, str(ROOT / 'environments/prepare_task.py'), '--task', task_id,
             '--profile-record', str(work / 'profiles' / (profile + '.json')),
             '--catalog', str(catalog), '--registry', repository])
        verify_task(json.loads(catalog.read_text())['tasks'][task_id])
        stamp.write_text(fingerprint + '\n')
        merged['tasks'].update(json.loads(catalog.read_text())['tasks'])
    target = work / 'catalog.json'
    if target.exists() and json.loads(target.read_text()) != merged:
        raise FileExistsError('Existing catalog differs; use a new output directory')
    if not target.exists():
        target.write_text(json.dumps(merged, indent=2) + '\n')
    print(json.dumps({'tasks_built': len(tasks), 'catalog': str(target), 'repository': repository}))


if __name__ == '__main__':
    main()
