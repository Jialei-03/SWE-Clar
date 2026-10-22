"""Create an immutable task image and private catalog for the maintained runtime."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def normalize_support_permissions(directory):
    """ZIP extraction need not preserve executable bits on browser launchers."""
    for launcher in sorted(list(directory.rglob('browser_launcher.py')) + list(directory.rglob('browser_launch.py'))):
        if launcher.is_symlink() or not launcher.is_file():
            raise ValueError('Browser launcher must be a regular support file')
        if not launcher.read_bytes().startswith(b'#!'):
            raise ValueError('Browser launcher needs an interpreter shebang')
        launcher.chmod(0o755)


def output(command):
    return subprocess.check_output(command, text=True).strip()


def inspect_image(reference, platform):
    # Older in-Pod Docker CLIs cannot filter image inspect by platform. Inspect
    # the local pinned image and validate its platform explicitly instead.
    image = json.loads(output(['docker', 'image', 'inspect', reference]))[0]
    parts = platform.split('/')
    if image.get('Os') != parts[0] or image.get('Architecture') != parts[1]:
        raise SystemExit('Prepared image platform mismatch')
    if len(parts) > 2 and image.get('Variant') != parts[2]:
        raise SystemExit('Prepared image variant mismatch')
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', required=True)
    parser.add_argument('--profile-record', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--registry', help='OCI registry/repository prefix used to publish immutable task images')
    args = parser.parse_args()
    task = ROOT / 'tasks' / args.task
    if task.parent != ROOT / 'tasks' or not task.is_dir():
        raise SystemExit('Unknown task ID')
    if args.catalog.resolve().is_relative_to(ROOT):
        raise SystemExit('Prepared runtime catalog must stay outside the dataset')
    env = json.loads((task / 'environment.json').read_text())
    gates = json.loads((task / 'evaluation/tests/expected_gates.json').read_text())['expected_gate_ids']
    if env['profile'] not in {'python-document-io', 'python-comfy', 'python-classroom', 'php-wordpress', 'php-editable-doc', 'python-cesium', 'python-report', 'python-web-mqtt', 'node-websocket', 'node-sdk', 'dotnet-sql', 'dotnet-sqlite', 'python-portal', 'python-media-score', 'python-crypto', 'python-web', 'native-control', 'native-wx', 'python-game', 'python-audio', 'python-listing','python-practice','python-calendar','flutter-component','flutter-websocket','flutter-firestore','python-watch','php-document','python-vision','python-media'}:
        raise SystemExit('Unsupported profile; provision the declared task environment')
    setup = env.get('flutter_workspace_setup', False)
    if not isinstance(setup, bool):
        raise SystemExit('flutter_workspace_setup must be boolean')
    if setup and (env['profile'] not in {'flutter-component', 'flutter-firestore'} or not (task / 'public_tests/preflight.py').is_file()):
        raise SystemExit('Prepared Flutter workspace needs its protected task preflight')
    task_check = env.get('task_preflight')
    if task_check is None and setup:
        task_check = ['python', '/public_tests/preflight.py', '--prepare-workspace']
    allowed_checks = [['python', '/public_tests/preflight.py'], ['python', '/public_tests/preflight.py', '--prepare-workspace']]
    if task_check is not None:
        if task_check not in allowed_checks or not (task / 'public_tests/preflight.py').is_file():
            raise SystemExit('Task preflight must use the protected declared entry')
        if task_check[-1] == '--prepare-workspace' and not setup:
            raise SystemExit('Flutter workspace setup must be explicitly declared')
    preflight_command = 'python -I /opt/sweclar/preflight.py'
    if task_check:
        preflight_command += ' && python -I ' + ' '.join(task_check[1:])
    profile = json.loads(args.profile_record.read_text())
    if profile['preflight']['passed'] is not True:
        raise SystemExit('Profile preflight has not passed')
    recipe = (ROOT / 'environments' / profile.get('recipe_subdirectory', env['profile'])).resolve()
    if not recipe.is_relative_to((ROOT / 'environments').resolve()):
        raise SystemExit('Recipe directory must remain inside environments')
    for name, digest in profile['recipe_hashes'].items():
        source = (recipe / name).resolve()
        if not source.is_relative_to(recipe):
            raise SystemExit('Recipe hash path escapes environment directory')
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != digest:
            raise SystemExit('Profile recipe changed; prepare it again before task creation')
    inspected = inspect_image(profile['image'], profile['platform'])
    if inspected['Architecture'] != profile['platform'].split('/')[-1]:
        raise SystemExit('Prepared image architecture mismatch')
    base = inspected['Id']
    if base != profile['image'] and not any(value.endswith('@' + profile['image']) for value in inspected.get('RepoDigests', [])):
        raise SystemExit('Prepared image digest mismatch')
    tag = (args.registry.rstrip('/') + '/' if args.registry else '') + 'sweclar-' + args.task.lower() + ':prepared-' + uuid.uuid4().hex[:16]
    with tempfile.TemporaryDirectory(prefix='sweclar-task-image-') as directory:
        context = Path(directory)
        support_file=task/'runtime_support.json'
        support=json.loads(support_file.read_text())['readable_public_files'] if support_file.exists() else []
        for name in support:
            if Path(name).name!=name or not name.endswith('_driver_test.dart') or not (task/'public_tests'/name).is_file():
                raise SystemExit('Unreviewed public runtime support path')
        # Candidate access is sealed by the runtime before restoring its patch.
        # Scoring-only transport files are exposed in a fresh disposable runtime.
        scoring_names = [str(p.relative_to(task/'public_tests')) for p in (task/'public_tests').rglob('*')
                         if p.is_file() and not any(part.startswith('__') for part in p.relative_to(task/'public_tests').parts)
                         and not (p.name.startswith(('test_', 'smoke', 'public_probe', 'preflight')) or p.suffix=='.md')]
        (context/'open_scoring_support.py').write_text(
            'from pathlib import Path\nroot=Path("/public_tests")\nroot.chmod(0o711)\n'
            'for name in '+repr(sorted(scoring_names))+':\n'
            ' p=root/name\n p.chmod(0o755 if p.stat().st_mode & 0o100 else 0o644)\n'
            ' for parent in p.parents:\n'
            '  if parent==root:break\n'
            '  parent.chmod(0o711)\n')
        for name, source in [('starter', task / 'workspace'), ('public_tests', task / 'public_tests')]:
            if any(p.is_symlink() for p in source.rglob('*')):
                raise SystemExit('Symlinked task material is not allowed')
            shutil.copytree(source, context / name)
        normalize_support_permissions(context / 'public_tests')
        local_base = 'sweclar-build-' + uuid.uuid4().hex + ':base'
        (context / 'Dockerfile').write_text(
            'FROM ' + local_base + '\n'
            + ('ENV HOME=/tmp/sweclar-home\n' if setup else '') +
            'COPY --chown=1000:1000 starter/ /workspace/\n'
            'COPY public_tests/ /opt/sweclar/sealed_support/\n'
            'COPY open_scoring_support.py /opt/sweclar/open_scoring_support.py\n'
            'RUN chmod -R go-rwx /opt/sweclar/sealed_support && mkdir -p /public_tests && chmod 700 /public_tests\n'
            'RUN for f in /opt/sweclar/harness.py /opt/sweclar/open_scoring_support.py; do if [ -f "$f" ]; then chmod go-rwx "$f"; fi; done && '
            'if [ -d /opt/sweclar/__pycache__ ]; then chmod -R go-rwx /opt/sweclar/__pycache__; fi\n'
            'RUN chown 1000:1000 /workspace\n'
            'USER 1000:1000\n'
            'RUN git init -q && git add -A && '
            'GIT_AUTHOR_DATE=2000-01-01T00:00:00Z GIT_COMMITTER_DATE=2000-01-01T00:00:00Z '
            'git -c user.name=Benchmark -c user.email=benchmark@example.test commit -qm "Independent starter"\n'
            'USER 0:0\n'
        )
        # Keep an immutable cache tag before removing the temporary alias. A
        # leaf profile can otherwise lose its only tag and disappear locally.
        retained_base = 'swe-clar-build-cache:' + inspected['Id'].removeprefix('sha256:')
        subprocess.run(['docker', 'tag', profile['image'], retained_base], check=True)
        if inspect_image(retained_base, profile['platform'])['Id'] != inspected['Id']:
            raise SystemExit('Retained base image identity mismatch')
        subprocess.run(['docker', 'tag', profile['image'], local_base], check=True)
        try:
            local = inspect_image(local_base, profile['platform'])
            if local['Id'] != inspected['Id'] or local['RootFS']['Layers'] != inspected['RootFS']['Layers']:
                raise SystemExit('Temporary local base does not match the pinned prepared image')
            subprocess.run(['docker', 'build', '--platform', profile['platform'], '--network', 'none', '--pull=false', '-t', tag, str(context)], check=True)
            derived = inspect_image(tag, profile['platform'])
            layers = inspected['RootFS']['Layers']
            if derived['RootFS']['Layers'][:len(layers)] != layers:
                raise SystemExit('Task image did not retain the verified base layers')
        finally:
            subprocess.run(['docker', 'image', 'rm', local_base], check=True, capture_output=True)
    if args.registry:
        subprocess.run(['docker', 'push', tag], check=True)
    image = inspect_image(tag, profile['platform'])
    reference = next((value for value in image.get('RepoDigests', []) if value.startswith(tag.rsplit(':', 1)[0] + '@')), None)
    if reference is None:
        raise SystemExit('Image store has no OCI manifest digest; supply --registry to publish the prepared image')
    commit = output(['docker', 'run', '--rm', '--platform', profile['platform'], '--network', 'none', '--user', '1000:1000', reference, 'git', 'rev-parse', 'HEAD'])
    files = {str(p.relative_to(task)): hashlib.sha256(p.read_bytes()).hexdigest()
             for directory in [task / 'workspace', task / 'public_tests']
             for p in sorted(directory.rglob('*')) if p.is_file()}
    public_digest = 'sha256:' + hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    spec = {
        'schema_version': 1, 'image_ref': reference, 'source_image_tag': tag, 'platform': profile['platform'],
        'workspace_path': '/workspace', 'base_commit': commit, 'candidate_uid': 1000,
        'public_materials_digest': public_digest,
        'phase_sealed_support': True,
        'preflight_command': preflight_command, 'network': 'none',
        'resources': {'cpus': env['resources']['cpus'], 'memory': str(env['resources']['memory_mb']) + 'm',
                      'pids_limit': env['resources']['pids'], 'shm_size': '256m',
                      'workspace_size': str(env['resources']['workspace_mb']) + 'm',
                      'temporary_size': '1024m', 'verifier_size': '128m',
                      'workspace_executable': env['profile'] in {'native-control', 'dotnet-sqlite', 'native-wx'}},
        'timeouts': {'prepare': 120, 'command': 120, 'export': 120, 'verifier': env['resources']['evaluation_wall_seconds']},
        'verifier': {'host_tests_path': 'evaluation/tests', 'container_path': '/private/tests',
                     'command': 'SWECLAR_LOG_DIR=/private/results python -I /private/tests/official_verifier.py',
                     'reward_path': '/private/results/reward.txt', 'gates_path': '/private/results/gates.json',
                     'expected_gate_ids': gates, 'gate_mapping': {gate: {'all_of': [gate]} for gate in gates}},
    }
    catalog = json.loads(args.catalog.read_text()) if args.catalog.exists() else {'tasks': {}}
    if args.task in catalog['tasks']:
        raise SystemExit('Use a new catalog to preserve already prepared experiment identities')
    catalog['tasks'][args.task] = spec
    args.catalog.parent.mkdir(parents=True, exist_ok=True)
    args.catalog.write_text(json.dumps(catalog, indent=2) + '\n')
    print(json.dumps({'task': args.task, 'image_ref': reference, 'catalog': str(args.catalog)}))


if __name__ == '__main__':
    main()
