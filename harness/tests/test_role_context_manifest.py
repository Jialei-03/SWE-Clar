"""Validate real task manifests through the same Node reader used by Pi."""
import hashlib
import json
from pathlib import Path
import subprocess

from runtime.delivery_contract import private_project_context
from runtime.registry import load_registry

ROOT=Path(__file__).resolve().parents[2]

def test_all_real_task_files_and_complete_cards_are_readable_and_private():
    bundles=[]
    for task in sorted((ROOT/'SWE-Clar/tasks').iterdir()):
        registry=load_registry(task)
        context,roots=private_project_context(task,registry)
        assert context['context_protocol']=='role-context.v3-elicitation'
        assert len(context['requirement_catalog'])==len(registry.slots)
        cards={r['virtual']:r['content'] for r in roots if 'content' in r}
        for reference,unit in zip(context['requirement_catalog'],registry.slots):
            card=json.loads(cards[reference['path']])
            assert card=={'name':unit.name,'content':unit.content,
                          'test_interface':unit.test_interface.model_dump(mode='json')}
        expected=[]
        for r in roots:
            if 'real' in r:
                if r.get('public_environment') is True:
                    assert Path(r['real']).is_relative_to((ROOT/'SWE-Clar/environments/amd64').resolve())
                    assert r['virtual'].startswith('/opt/sweclar/')
                else:
                    assert Path(r['real']).is_relative_to(task.resolve())
                for name,digest in r['files'].items():
                    expected.append({'path':r['virtual']+('/'+name if name else ''),'sha256':digest})
            else:
                expected.append({'path':r['virtual'],'sha256':hashlib.sha256(r['content'].encode()).hexdigest()})
        for relative,virtual in [('workspace','/workspace'),('public_tests','/public_tests'),
                                 ('attachments',context['workspace_path']+'/task_attachments'),('evaluation/tests','/private_acceptance')]:
            actual={virtual+'/'+p.relative_to(task/relative).as_posix()
                    for p in (task/relative).rglob('*') if p.is_file()
                    and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
            assert actual <= {e['path'] for e in expected}
        bundles.append({'read_roots':roots,'expected':expected})
    script='''
import {mappedReadOperations,mappedWorkingDirectory} from './harness/pi/mapped_read.mjs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
let input='';for await(const chunk of process.stdin)input+=chunk;
for(const bundle of JSON.parse(input)){
 const reader=mappedReadOperations(bundle);
 assert.ok((await reader.readFile('/project_documents/README.md')).length>0);
 for(const e of bundle.expected){
   const data=await reader.readFile(e.path);
   assert.equal(createHash('sha256').update(data).digest('hex'),e.sha256);
 }
 for(const forbidden of ['/evaluation/requirement_units.yaml','/evaluation/reference_solution.py',
   '/etc/passwd','/workspace/../evaluation/requirement_units.yaml','/results/output.json'])
   await assert.rejects(()=>reader.readFile(forbidden));
}
'''
    result=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(bundles),
                          text=True,capture_output=True,cwd=ROOT,timeout=120)
    assert result.returncode==0,result.stderr
