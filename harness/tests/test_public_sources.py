import json
from pathlib import Path
import subprocess
import hashlib
import pytest

from runtime.public_sources import public_source_roots
from runtime.delivery_contract import private_project_context
from runtime.delivery_contract import load_delivery_contract
from runtime.registry import load_registry
from runtime.task_input import build_initial_task_input

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / 'SWE-Clar/tasks'

def test_public_source_catalog_is_bound_to_the_delivery_contract(monkeypatch):
    import runtime.public_sources as sources
    task = TASKS / 'SWECLAR-045'
    registry = load_registry(task)
    assert load_delivery_contract(task,registry)['public_environment_sha256']
    monkeypatch.setattr(sources,'public_source_digest',lambda task: '0'*64)
    with pytest.raises(ValueError,match='manifest changed without contract review'):
        load_delivery_contract(task,registry)

def test_environment_manifest_rejects_source_drift_and_path_escape(tmp_path):
    task = tmp_path / 'tasks/SWECLAR-001'
    task.mkdir(parents=True)
    (task / 'environment.json').write_text(json.dumps({'profile':'sample','platform':'linux/amd64'}))
    recipe = tmp_path / 'environments/amd64/sample'
    recipe.mkdir(parents=True)
    source = recipe / 'provider.py'
    source.write_text('public source')
    entry = {'source':'environments/amd64/sample/provider.py',
             'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    document = {'schema_version':1,'platform':'linux/amd64',
                'profiles':{'sample':{'/opt/sweclar/provider.py':entry}}}
    manifest = tmp_path / 'environments/public_source_manifest.json'
    manifest.write_text(json.dumps(document))
    assert len(public_source_roots(task)) == 1
    source.write_text('modified source')
    with pytest.raises(ValueError, match='hash mismatch'):
        public_source_roots(task)
    entry['source'] = 'tasks/SWECLAR-001/environment.json'
    manifest.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='escapes'):
        public_source_roots(task)
    entry['source'] = 'environments/amd64/sample/provider.py'
    document['profiles']['sample'] = {'/opt/sweclar/../../private/answers':entry}
    manifest.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='virtual path'):
        public_source_roots(task)

def test_all_public_environment_sources_read_through_actual_private_reader():
    bundles = [public_source_roots(task) for task in sorted(TASKS.iterdir())]
    script = '''
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mappedReadOperations} from './harness/pi/mapped_read.mjs';
let input='';for await(const chunk of process.stdin)input+=chunk;
for(const roots of JSON.parse(input)){
 const reader=mappedReadOperations({read_roots:roots});
 for(const root of roots){
  const data=await reader.readFile(root.virtual);
  assert.equal(createHash('sha256').update(data).digest('hex'),root.files['']);
 }
 await assert.rejects(()=>reader.readFile('/opt/sweclar/unlisted-secret.py'));
 await assert.rejects(()=>reader.readFile('/private/tests/answers.py'));
}
'''
    result = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps(bundles),
                            text=True, capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr

def test_public_dependency_closure_is_available_to_private_roles_and_candidate():
    task = TASKS / 'SWECLAR-001'
    registry = load_registry(task)
    sources = public_source_roots(task)
    paths = {r['virtual'] for r in sources}
    assert {'/opt/sweclar/harness.py', '/opt/sweclar/offer_service.py'} <= paths
    context, roots = private_project_context(task, registry)
    assert paths <= {r['virtual'] for r in roots}
    assert paths <= {f['path'] for f in context['file_catalog']}
    initial = build_initial_task_input(task, registry)
    # Elicitation policy: available through read tools, not pre-disclosed in the initial prompt.
    assert '/opt/sweclar/offer_service.py' not in initial.public_task
    assert 'DELIVERY_INTERFACE.json' not in initial.public_task
    assert initial.visible_requirement_unit_ids == []
    assert initial.public_test_paths == []
    assert '/private_acceptance' not in initial.public_task

def test_all_runtime_public_paths_are_read_only_exact_files():
    bundles = [{'runtime_workspace': '/workspace',
                'runtime_public_read_files': {r['virtual']: r['files'][''] for r in public_source_roots(task)}}
               for task in sorted(TASKS.iterdir())]
    script = '''
import assert from 'node:assert/strict';
import {runtimePath} from './harness/pi/runtime_operations.mjs';
let input='';for await(const chunk of process.stdin)input+=chunk;
for(const bundle of JSON.parse(input)){
 for(const filename of Object.keys(bundle.runtime_public_read_files)){
  assert.equal(runtimePath(bundle,filename,{publicRead:true}),filename);
  assert.throws(()=>runtimePath(bundle,filename));
 }
 for(const forbidden of ['/opt/sweclar/unreviewed.py','/private/tests/answers.py','/etc/passwd'])
  assert.throws(()=>runtimePath(bundle,forbidden,{publicRead:true}));
}
'''
    result = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps(bundles),
                            text=True, capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr
