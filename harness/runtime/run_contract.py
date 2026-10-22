"""Content-addressed inputs checked before every model-backed workflow step."""

import json
import os
from pathlib import Path

from .canonical import digest_bytes, digest_json

_CACHE_PARTS = {'__pycache__', '.pytest_cache', '.DS_Store'}


def file_inventory(root: Path) -> dict[str, str]:
  """Hash exact task bytes; never follow links outside the release bundle."""
  inventory = {}
  if root.is_symlink():
    raise ValueError('Frozen input root is a symbolic link')
  for path in sorted(root.rglob('*')):
    relative = path.relative_to(root)
    if any(part in _CACHE_PARTS for part in relative.parts):
      continue
    if path.is_symlink():
      raise ValueError(f'Frozen input contains a symbolic link: {relative}')
    if path.is_file():
      inventory[relative.as_posix()] = digest_bytes(path.read_bytes())
  if not inventory:
    raise ValueError(f'Frozen input is empty: {root}')
  return inventory


def execution_contract(framework: Path, task: Path, profiles: dict, runtime: dict) -> dict:
  """Keep secrets outside the contract; caller supplies public profile snapshots."""
  source_files = [
    *framework.glob('*.py'),
    *framework.joinpath('runtime').glob('*.py'),
    *framework.joinpath('pi').glob('*.mjs'),
  ]
  source_files += [
    framework / name
    for name in ['requirements.txt', 'pi/package.json', 'pi/package-lock.json']
    if (framework / name).is_file()
  ]
  source = {
    path.relative_to(framework).as_posix(): digest_bytes(path.read_bytes())
    for path in sorted(source_files)
    if not path.name.endswith('.test.mjs')
  }
  if not source:
    raise ValueError('No execution source files found')
  root = task.parent.parent
  if task.parent.name == 'tasks' and root.name == 'processed':
    root = root.parent
  dataset = root / 'dataset.json'
  if not dataset.is_file():
    dataset = root / 'README.md'
  if not dataset.is_file():
    raise ValueError('Execution requires release README.md')
  task_files = file_inventory(task)
  manifest_path = root / 'release-manifest.json'
  if os.environ.get('SWECLAR_REQUIRE_RELEASE_MANIFEST') == '1' and not manifest_path.is_file() and not (task / 'evaluation/requirement_units.yaml').is_file():
    raise ValueError('Published execution requires release-manifest.json')
  release_digest = None
  if manifest_path.is_file():
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    expected = manifest['source_files']
    prefix = task.relative_to(root).as_posix() + '/'
    if task_files != {
      name.removeprefix(prefix): value
      for name, value in expected.items()
      if name.startswith(prefix)
    }:
      raise ValueError('Task bytes differ from the published release')
    if digest_bytes(dataset.read_bytes()) != expected[dataset.name]:
      raise ValueError('Dataset membership differs from the published release')
    release_digest = digest_bytes(manifest_bytes)
  return {
    'schema_version': 1,
    'code_digest': digest_json(source),
    'dataset_digest': digest_bytes(dataset.read_bytes()),
    'task_digest': digest_json(task_files),
    'release_digest': release_digest,
    'runtime_digest': digest_json(runtime),
    'profiles': profiles,
  }
