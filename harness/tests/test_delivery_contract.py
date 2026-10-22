import copy
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

from runtime.delivery_contract import load_delivery_contract,private_project_context,require_experiment_ready
from runtime.registry import load_registry
from runtime.task_input import build_initial_task_input
from runtime.client import SupervisedClientSimulator,ClientSimulationError
from runtime.step_engine import _model_visible_dialogue_messages
from runtime.audit import _reference_answer

DATA=Path(__file__).resolve().parents[2]/'SWE-Clar'

@pytest.mark.parametrize('task',sorted((DATA/'tasks').iterdir()),ids=lambda p:p.name)
def test_all_task_projections_and_binding(task):
    reg=load_registry(task)
    doc=load_delivery_contract(task,reg)
    assert len(doc['interfaces_by_ru'])==len(reg.slots)
    initial=build_initial_task_input(task,reg)
    assert not any('evaluation/' in p for p in initial.starter_code_paths)
    assert 'workspace/DELIVERY_INTERFACE.json' not in initial.starter_code_paths
    assert (task/'evaluation/project/DELIVERY_INTERFACE.json').is_file()
    assert 'interfaces_by_ru' not in json.dumps(doc['public'])

@pytest.mark.parametrize('relative',['evaluation/project/README.md','evaluation/project/DELIVERY_INTERFACE.json',
                                   'evaluation/tests/test_levels.py','evaluation/requirement_units.yaml'])
def test_drift_fails_closed(tmp_path,relative):
    target=tmp_path/'SWECLAR-053';shutil.copytree(DATA/'tasks/SWECLAR-053',target)
    path=target/relative
    if path.suffix=='.json':
        d=json.loads(path.read_text());d['task_id']='incorrect';path.write_text(json.dumps(d))
    else:path.write_text(path.read_text()+'\n# drift\n')
    with pytest.raises(ValueError):load_delivery_contract(target,load_registry(target))

def test_same_grounding_and_private_trace_not_candidate_input():
    task=DATA/'tasks/SWECLAR-053';reg=load_registry(task)
    context,roots=private_project_context(task,reg);seen=[]
    class Client:
        def draft(self,payload):
            seen.append(payload);return {'message':'Use side, price, index; index is zero-based.'}
    class Supervisor:
        def review(self,payload):
            seen.append(payload);return {'decision':'approve','reason':'Matches agreement',
                                        'violations':[],'rewrite_instruction':None}
    render=SupervisedClientSimulator(reg,Client(),Supervisor(),project_context=context).respond(
        public_task='Rolling levels',candidate_message='Is it index or bar_index?',
        approved_history=[],previously_disclosed_hidden_ru_ids=[])
    assert seen[0]['project_context']==seen[1]['project_context']==context
    assert {'/workspace','/public_tests','/private_acceptance'} <= {r['virtual'] for r in roots}
    assert 'bar_index' in json.dumps(roots) and 'test_levels.py' in json.dumps(context)
    assert 'public_delivery_agreement' not in context
    assert all('content' in u and 'test_interface' in u for u in seen[0]['requirement_units'])
    visible=_model_visible_dialogue_messages([{'role':'client','content':render.text,
                 'supervision_attempts':[{'private_source':'PRIVATE_CANARY_123'}],
                 'client_trace':{'private_source':'PRIVATE_CANARY_123'}}])
    assert 'PRIVATE_CANARY_123' not in json.dumps(visible)
    assert 'test_levels.py' not in json.dumps(visible)

def test_contract_conflict_blocks_reply():
    reg=load_registry(DATA/'tasks/SWECLAR-053')
    class Client:
        def draft(self,p):return {'message':'Use the other key.'}
    class Supervisor:
        def review(self,p):return {'decision':'revise','reason':'Source contradiction',
                                  'violations':['contract_conflict'],'rewrite_instruction':'Maintainer review'}
    with pytest.raises(ClientSimulationError) as err:
        SupervisedClientSimulator(reg,Client(),Supervisor()).respond(public_task='task',candidate_message='Which key?',approved_history=[],previously_disclosed_hidden_ru_ids=[])
    assert err.value.code=='client.contract_conflict' and err.value.retryable is False
    assert len(err.value.attempts)==1 and 'contract_conflict' in err.value.attempts[0].violations

def test_client_text_is_supervised_without_automatic_interface_appendix():
    task=DATA/'tasks/SWECLAR-053';reg=load_registry(task)
    context,_=private_project_context(task,reg);seen=[]
    name=reg.slots[-1].name
    class Client:
        def draft(self,p): return {'message':'Use index, not bar_index.', 'interface_names':[name]}
    class Supervisor:
        def review(self,p):
            seen.append(p['client_draft'])
            assert p['client_draft']=='Use index, not bar_index.'
            return {'decision':'approve','reason':'Exact interface attached','violations':[],'rewrite_instruction':None}
    render=SupervisedClientSimulator(reg,Client(),Supervisor(),project_context=context).respond(
        public_task='levels',candidate_message='Which event fields?',approved_history=[],previously_disclosed_hidden_ru_ids=[])
    assert seen==[render.text]
    assert render.text=='Use index, not bar_index.'
    assert 'RU-006' not in render.text and '/private_acceptance' not in render.text

def test_hidden_projection_injection_rejected(tmp_path):
    from runtime.delivery_contract import public_projection,readme_projection
    target=tmp_path/'SWECLAR-013';shutil.copytree(DATA/'tasks/SWECLAR-013',target)
    reg=load_registry(target)
    path=target/'evaluation/delivery_contract.json';d=json.loads(path.read_text())
    d['public']['interfaces'].append({'type':'function','entry':{'function':'private_fake'},'output':'secret'})
    path.write_text(json.dumps(d));(target/'evaluation/project/README.md').write_text(readme_projection(d))
    (target/'evaluation/project/DELIVERY_INTERFACE.json').write_text(json.dumps(public_projection(d)))
    (target/'workspace/DELIVERY_INTERFACE.json').write_text(json.dumps(public_projection(d)))
    with pytest.raises(ValueError,match='leaked into workspace'):load_delivery_contract(target,reg)

def test_audit_judge_also_receives_exact_interface():
    reg=load_registry(DATA/'tasks/SWECLAR-053')
    answer=_reference_answer(reg.slots[-1])
    assert answer['agreed_delivery_interface']['output']['record_schemas']['break_event']['required']==['side','price','index']

def test_client_conflict_is_private_and_nonretryable():
    task=DATA/'tasks/SWECLAR-053';reg=load_registry(task);ctx,_=private_project_context(task,reg)
    class Client:
        def draft(self,p):return {'message':'Pending review','interface_names':[], 'contract_conflict':'PRIVATE conflict evidence'}
    class Supervisor:
        def review(self,p):return {'decision':'revise','reason':'Conflicting authority','violations':['contract_conflict'],'rewrite_instruction':'Maintainer review'}
    with pytest.raises(ClientSimulationError) as err:
        SupervisedClientSimulator(reg,Client(),Supervisor(),project_context=ctx).respond(
            public_task='task',candidate_message='Which key?',approved_history=[],previously_disclosed_hidden_ru_ids=[])
    assert err.value.code=='client.contract_conflict' and not err.value.retryable
    assert err.value.attempts[-1].reason=='Conflicting authority'

def test_role_transport_keeps_private_read_trace(monkeypatch):
    from runtime.role_adapters import ClientSimulatorTransport
    from llm import RoleConfig,LLMResult
    seen=[]
    def fake_chat(config,system,messages,max_retries,**kwargs):
        seen.append(kwargs)
        return LLMResult(text='{"message":"Use index.","interface_names":[]}',usage={},latency_s=0,
              raw_stop_reason='stop',raw_message={'private_tool_trace':{'tool_call_count':1,'tool_events':[{'tool':'read','output':'PRIVATE_SOURCE'}]}})
    monkeypatch.setattr('runtime.role_adapters.chat',fake_chat)
    roots=[{'virtual':'/private_acceptance','real':'/frozen/task/tests'}]
    adapter=ClientSimulatorTransport(RoleConfig(api_style='pi'),read_roots=roots)
    assert adapter.draft({'project_context':{'contract_version':'v-test'}})['message']=='Use index.'
    assert seen==[{'read_roots':roots}]
    assert adapter.last_trace['request']['tool_permissions']==['read']
    assert adapter.last_trace['tool_call_count']==1

def test_non_pi_private_read_fails_without_network():
    from llm import chat,RoleConfig,LLMError
    with pytest.raises(LLMError,match='requires the Pi'):
        chat(RoleConfig(),'',[],read_roots=[{'virtual':'/private_acceptance','real':'/x'}])

def test_unqualified_release_cannot_launch(tmp_path):
    (tmp_path/'release_status.json').write_text(json.dumps({'experiment_ready':False}))
    with pytest.raises(ValueError,match='review-only'): require_experiment_ready(tmp_path)

def test_runtime_workspace_must_match_declared_task_workdir():
    task=DATA/'tasks/SWECLAR-053'
    with pytest.raises(ValueError,match='Runtime workspace differs'):
        private_project_context(task,load_registry(task),workspace='/workspace/project')

def test_publisher_mutation_supports_literal_encoded_and_derived_keys():
    p=DATA/'tasks/SWECLAR-024/evaluation/tests/publisher_contract.py'
    spec=importlib.util.spec_from_file_location('publisher_contract',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    from urllib.parse import urlsplit
    for url,key in [('rtmp://127.0.0.1:9000/live/demo-beta','demo-beta'),
                    ('rtmp://127.0.0.1:9000/live?secret=a%2Fb','a/b'),
                    ('rtmp://127.0.0.1:9000/publish/fed123456789','demo-beta'),
                    ('rtmp://127.0.0.1:9000/publish?secret=derived123','demo-beta')]:
        wrong=m.invalid_publisher_url(url,key)
        assert wrong!=url
        assert urlsplit(wrong).netloc==urlsplit(url).netloc

def test_optional_fields_are_optional_in_033_tests():
    import ast
    p=DATA/'tasks/SWECLAR-033/evaluation/tests/test_solution.py'
    tree=ast.parse(p.read_text())
    check=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='check_actual_wire_format')
    assertion=next(n for n in ast.walk(check) if isinstance(n,ast.Assert) and 'manual_entry_required' in ast.unparse(n.test))
    expr=compile(ast.Expression(assertion.test),str(p),'eval')
    assert eval(expr,{}, {'rows':[{}],'out':{'result':{'updated':1}}})
    assert eval(expr,{}, {'rows':[{}],'out':{'result':{'updated':1,'manual_entry_required':False}}})
    assert not eval(expr,{}, {'rows':[{}],'out':{'result':{'manual_entry_required':True}}})
