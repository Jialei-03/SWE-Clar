from pathlib import Path
import json
import pytest
from runtime.online_annotations import RUAnnotation, validate_annotations, summarize_annotations
from runtime.observations import candidate_observations
from runtime.registry import load_registry
from runtime.freeze import freeze_context, create_branch_envelope, model_visible_frozen_context
from runtime.artifacts import ArtifactStore
from runtime.audit import build_semantic_judge_payload, validate_audit_output
from runtime.role_adapters import DisclosureSupervisorTransport
from llm import RoleConfig, LLMResult
import prompts
ROOT=Path(__file__).resolve().parents[2]/'SWE-Clar'

def test_freeze_preserves_observations_without_private_reviews(tmp_path):
    messages=[{'message_id':'q1','role':'candidate','content':'Question',
               'model_trace':{'messages':[{'role':'user','content':'old payload'},
                                          {'role':'assistant','content':'inspection'},
                                          {'role':'toolResult','content':'x'*20000}],
                              'tool_events':[{'name':'read','output':'actual output'}]}},
              {'message_id':'c1','role':'client','content':'Approved',
               'supervision_attempts':[{'client_draft':'PRIVATE REJECTED DRAFT'}],
               'ru_annotations':[{'content':'PRIVATE RU'}]}]
    history=candidate_observations(messages)
    assert len(history[0]['messages'][1]['content'])==20000
    assert 'old payload' not in json.dumps(history)
    assert 'PRIVATE' not in json.dumps(history)
    frozen=freeze_context(task_id='t',question_atom_limit=None,public_task='task',
        messages=[{'role':'candidate','content':'Question'},{'role':'client','content':'Approved'}],
        exposure_ledger=[{'secret':'PRIVATE'}],source_catalog=[],attachments=[],
        candidate_config_digest='sha256:'+'0'*64,artifacts=ArtifactStore(tmp_path),
        candidate_observation_history=history)
    evidence=model_visible_frozen_context(frozen)['evidence']
    assert evidence['candidate_observations']==history
    assert 'PRIVATE' not in json.dumps(evidence)
    assert create_branch_envelope(frozen,'audit','answer').tool_permissions==['read','submit_audit_answers']

def test_audit_judge_is_content_only_and_manifest_unweighted():
    from runtime.manifests import manifest_from_registry
    reg=load_registry(ROOT/'tasks/SWECLAR-013')
    answers=validate_audit_output({'answers':[{'slot_id':u.slot_id,'status':'known','value':'inferred answer','source_refs':[],'confidence':0.6} for u in reg.slots]},reg)
    payload=build_semantic_judge_payload(answers,reg)
    assert 'frozen_evidence' not in payload
    assert len(payload['items'])==len(reg.slots)
    assert 'Do not require supporting evidence' in prompts.AUDIT_JUDGE_SYSTEM
    assert all('weight' not in t for t in manifest_from_registry(reg).model_dump()['tests'])

def test_online_summary_counts_only_hidden_complete_and_partial():
    reg=load_registry(ROOT/'tasks/SWECLAR-013')
    hidden=[u.slot_id for u in reg.slots if not u.initially_visible]
    rows=[dict(ru_id=u.slot_id,status='complete' if u.slot_id==hidden[0] else 'partial',agent_mentions_current=True,client_mentions_current=True) for u in reg.slots]
    summary=summarize_annotations(reg,{'messages':[{'role':'client','message_id':'c','candidate_message_id':'q','ru_annotations':rows}]},'clarify')
    assert summary['hidden_complete_count']==1
    assert summary['hidden_partial_count']==len(hidden)-1
    assert summary['mention_counts_by_ru'][hidden[0]]=={'candidate':1,'client':1,'total':2}
    assert summarize_annotations(reg,{},'oracle')['status']=='not_applicable'

def test_three_stage_flow_preserves_tool_history_and_separates_audit(tmp_path):
    from runtime.step_engine import StepEngine
    from runtime.storage import SessionRepository
    from runtime.dialogue import DialogueService
    from runtime.manifests import manifest_from_registry
    from runtime.task_input import build_initial_task_input
    reg=load_registry(ROOT/'tasks/SWECLAR-013');manifest=manifest_from_registry(reg)
    initial=build_initial_task_input(ROOT/'tasks/SWECLAR-013',reg)
    audit_seen=[];coding_seen=[];judge_seen=[]
    class Candidate:
        last_trace={'messages':[{'role':'assistant','content':'I inspected the starter.'},
                                {'role':'toolResult','toolName':'read','content':'OBSERVED PUBLIC CODE'}]}
        def __call__(self,context):return '{"action":"ready"}'
    def audit(ctx):
        audit_seen.append(ctx)
        return {'answers':[{'slot_id':u.slot_id,'status':'known','value':'UNIQUE AUDIT ANSWER','source_refs':[],'confidence':1} for u in reg.slots]}
    def judge(ctx):
        judge_seen.append(ctx)
        return {'verdicts':[{'slot_id':u.slot_id,'content_correct':True,'reason':'Correct inference.'} for u in reg.slots]}
    def coding(ctx):
        coding_seen.append(ctx)
        return {'done':True,'message':'done','delivery_session_id':'delivery','usage':{}}
    engine=StepEngine(repository=SessionRepository(tmp_path/'db'),artifacts=ArtifactStore(tmp_path/'artifacts'),registry=reg,manifest=manifest,
        dialogue_service_factory=lambda repo,registry:DialogueService(repo,registry),candidate_turn=Candidate(),audit_turn=audit,audit_judge=judge,
        coding_step=coding,coding_evaluator=lambda ctx:{'test_results':{t.id:{'passed':True,'skipped':False} for t in manifest.tests}},
        public_task=initial.public_task,source_catalog=initial.source_catalog,attachments=[],candidate_config_digest='sha256:'+'1'*64)
    run=engine.create_run(None,benchmark_mode='clarify')
    for _ in range(8):
        if run['status'] in engine.TERMINAL:break
        run=engine.step(run['session_id'])
    assert run['status']=='succeeded',run.get('errors')
    assert 'OBSERVED PUBLIC CODE' in json.dumps(audit_seen[0])
    assert 'frozen_evidence' not in judge_seen[0]
    # Coding transport projects only the frozen_context; the research session
    # remains in its controller context but is never serialised to the model.
    assert 'OBSERVED PUBLIC CODE' in json.dumps(coding_seen[0]['frozen_context'])
    assert 'UNIQUE AUDIT ANSWER' not in json.dumps(coding_seen[0]['frozen_context'])
    assert run['branches']['audit']['metrics']['requirement_understanding_accuracy']==1


def test_checkpoint_retries_stop_after_five_without_rerunning_scores():
    from runtime.retries import advance
    class Repository:
        state={'cursor':'audit.agent','status':'running','steps':[{'status':'failed_retryable','error':{'retryable':True,'code':'network'}}]}
        def get_session(self,sid):return self.state
    class Engine:
        repository=Repository();calls=0
        def _patch(self,sid,patch):self.repository.state.update(patch)
        def retry(self,sid):self.calls+=1;return self.repository.state
    engine=Engine()
    for _ in range(6):run=advance(engine,'test')
    assert engine.calls==5
    assert run['status']=='failed' and run['runner_error']['code']=='retry_exhausted'

def test_pi_role_transport_does_not_disguise_truncated_output(monkeypatch):
    from llm import chat
    monkeypatch.setattr('runtime.pi_adapters._run_pi_text',lambda *a,**k:{'final_text':'partial','final_message':{'stop_reason':'length'},'usage':{}})
    result=chat(RoleConfig(api_style='pi',model='fixture'), 'system', [])
    assert result.raw_stop_reason=='length'

def test_pre_compaction_assistant_and_tool_results_are_not_lost():
    trace={'messages':[{'role':'assistant','timestamp':2,'content':'recent'}],
           'turns':[{'assistant':{'timestamp':1,'text':'earlier understanding','thinking':'earlier reasoning'},'tool_results':[{'content':'earlier tool result'}]},
                    {'assistant':{'timestamp':2,'text':'recent'}}]}
    history=candidate_observations([{'role':'candidate','message_id':'q','model_trace':trace}])
    assert len(history[0]['pre_compaction_turns'])==1
    assert 'earlier understanding' in json.dumps(history)
    assert 'earlier tool result' in json.dumps(history)
