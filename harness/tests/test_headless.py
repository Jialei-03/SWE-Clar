from pathlib import Path
import json
import pytest
from runtime.registry import load_registry
from runtime.task_input import build_initial_task_input
from runtime.manifests import manifest_from_registry
from runtime.step_engine import StepEngine
from runtime.artifacts import ArtifactStore
from runtime.storage import SessionRepository
from runtime.dialogue import DialogueService
from runtime.run_contract import execution_contract
from runtime.execution import ExecutionContext
from runtime.composition import build_engine
from runtime.actions import ReadyAction
ROOT=Path(__file__).resolve().parents[2]/'SWE-Clar'

def test_new_layout_has_only_public_inputs():
    task=ROOT/'tasks/SWECLAR-013'
    registry=load_registry(task)
    initial=build_initial_task_input(task,registry)
    assert initial.starter_code_paths
    assert all(p.startswith('workspace/') for p in initial.starter_code_paths)
    assert 'strictly more than 60' not in initial.public_task
    assert not any('evaluation/' in p for p in initial.starter_code_paths+initial.public_test_paths)
    assert initial.public_test_paths==[]
    assert 'Agreed delivery interface' not in initial.public_task

def test_contract_without_metadata_json():
    task=ROOT/'tasks/SWECLAR-013'
    contract=execution_contract(Path(__file__).resolve().parents[1],task,{}, {})
    assert contract['task_digest'].startswith('sha256:')
    assert contract['dataset_digest'].startswith('sha256:')

@pytest.mark.parametrize('mode',['direct','clarify','oracle'])
def test_three_modes_complete_without_server(tmp_path,mode):
    task=ROOT/'tasks/SWECLAR-013'
    registry=load_registry(task);manifest=manifest_from_registry(registry)
    initial=build_initial_task_input(task,registry)
    seen=[]
    def audit(ctx):
        seen.append(ctx)
        return {'answers':[{'slot_id':u.slot_id,'status':'unknown','value':None,'source_refs':[],'confidence':0} for u in registry.slots]}
    engine=StepEngine(repository=SessionRepository(tmp_path/'state.sqlite'),artifacts=ArtifactStore(tmp_path/'artifacts'),
        registry=registry,manifest=manifest,
        dialogue_service_factory=lambda r,g:DialogueService(r,g),
        candidate_turn=lambda ctx:'{"action":"ready"}',
        audit_turn=audit,
        coding_step=lambda ctx:{'done':True,'message':'fixture delivery','delivery_session_id':'fixture','usage':{}},
        coding_evaluator=lambda ctx:{'test_results':{t.id:{'passed':True,'skipped':False} for t in manifest.tests}},
        public_task=initial.public_task,source_catalog=initial.source_catalog,attachments=[],
        candidate_config_digest='sha256:'+'1'*64)
    run=engine.create_run(None if mode=='clarify' else 0,benchmark_mode=mode)
    run=engine.finish_initialization(run['session_id'])
    for _ in range(8):
        if run['status'] in engine.TERMINAL:break
        run=engine.step(run['session_id'])
    assert run['status']=='succeeded',run.get('evaluation_error')
    assert seen
    evidence=seen[0]['frozen_context']['evidence']
    assert 'exposure_ledger' not in evidence
    assert ('strictly more than 60' in json.dumps(evidence))==(mode=='oracle')


def test_host_credentials_not_forwarded_to_tools(tmp_path,monkeypatch):
    monkeypatch.setenv('CLIENT_API_KEY','must-not-enter-candidate')
    context=ExecutionContext(tasks_dir=ROOT/'tasks',workdirs_dir=tmp_path,auth_path=tmp_path/'auth.json')
    assert 'CLIENT_API_KEY' not in context.tool_env

def test_optional_attachment_stays_in_allowed_root(tmp_path):
    from runtime.composition import _runtime_ru_attachment_source
    (tmp_path/'evaluation').mkdir()
    (tmp_path/'evaluation/requirement_units.yaml').write_text('schema_version: 1')
    (tmp_path/'attachments').mkdir()
    f=tmp_path/'attachments/public.txt';f.write_text('example')
    assert _runtime_ru_attachment_source(tmp_path,'task_attachments/public.txt')==f
    with pytest.raises(RuntimeError):
        _runtime_ru_attachment_source(tmp_path,'task_attachments/../evaluation/requirement_units.yaml')

def test_fifth_client_draft_can_be_approved_without_annotations():
    from runtime.client import SupervisedClientSimulator
    registry=load_registry(ROOT/'tasks/SWECLAR-013')
    class Client:
        def draft(self,payload):
            return {'message':'The account list is ordered by account ID.'}
    class Supervisor:
        calls=0
        def review(self,payload):
            self.calls+=1
            if self.calls<5:
                return {'decision':'revise','reason':'Clarify wording','rewrite_instruction':'State the same fact clearly.'}
            return {'decision':'approve','reason':'Consistent with the task.'}
    supervisor=Supervisor()
    result=SupervisedClientSimulator(registry,Client(),supervisor).respond(
        public_task='Account application',candidate_message='How is the account list ordered?',
        approved_history=[],previously_disclosed_hidden_ru_ids=[])
    assert len(result.attempts)==5
    assert result.attempts[-1].decision=='approve'
    assert result.attempts[-1].annotation_status=='unavailable'
