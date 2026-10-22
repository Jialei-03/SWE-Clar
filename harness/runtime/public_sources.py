"""Exact, frozen public environment sources, shared by every role's read path."""
import hashlib
import json
from pathlib import Path, PurePosixPath

def public_source_digest(task_dir):
    roots = public_source_roots(task_dir)
    manifest = Path(task_dir).resolve().parent.parent / 'environments/public_source_manifest.json'
    if not manifest.is_file():
        return None
    projection = {item['virtual']:item['files'][''] for item in roots}
    return hashlib.sha256(json.dumps(projection, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def public_source_roots(task_dir):
    task = Path(task_dir).resolve()
    dataset = task.parent.parent
    manifest = dataset / 'environments/public_source_manifest.json'
    if not manifest.is_file():
        release = dataset / 'release_status.json'
        if release.is_file() and json.loads(release.read_text()).get('version') == 'swe-clar':
            raise ValueError('Review dataset is missing its frozen public environment manifest')
        return []  # Standalone task fixtures have no environment catalog.
    document = json.loads(manifest.read_text())
    environment = json.loads((task / 'environment.json').read_text())
    if document.get('schema_version') != 1 or document.get('platform') != environment.get('platform'):
        raise ValueError('Public environment manifest platform/schema mismatch')
    profile = environment['profile']
    if profile not in document['profiles']:
        raise ValueError('Public environment profile is missing')
    roots = []
    for virtual, item in document['profiles'][profile].items():
        path = PurePosixPath(virtual)
        if not virtual.startswith('/opt/sweclar/') or '..' in path.parts or str(path) != virtual:
            raise ValueError('Unsafe public environment virtual path')
        source = dataset / item['source']
        if source.is_symlink() or not source.resolve().is_relative_to((dataset / 'environments/amd64').resolve()):
            raise ValueError('Public environment source escapes frozen recipe tree')
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != item['sha256']:
            raise ValueError('Public environment source hash mismatch')
        roots.append({'virtual': virtual, 'real': str(source.resolve()),
                      'files': {'': item['sha256']}, 'public_environment': True})
    return roots
