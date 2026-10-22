import json
from pathlib import Path
import pytest
from llm import RoleConfig,LLMResult
from runtime.role_adapters import DisclosureSupervisorTransport
from runtime.client import SupervisedClientSimulator
from runtime.registry import load_registry
from runtime.online_annotations import summarize_annotations
from runtime.retries import advance,should_continue
ROOT=Path(__file__).resolve().parents[2]/'SWE-Clar'

def rows(reg,status='complete'):
 return [dict(ru_id=u.slot_id,status=status,agent_mentions_current=True,client_mentions_current=True) for u in reg.slots]

@pytest.mark.parametrize('annotation',[None,[],{'bad':'shape'},[{'ru_id':'unknown'}]])
def test_bad_statistics_never_retry_or_reject_valid_reply(monkeypatch,annotation):
 reg=load_registry(ROOT/'tasks/SWECLAR-013');calls=[]
 def chat(config,system,messages,max_retries):
  payload=json.loads(messages[0]['content']);calls.append(payload)
  assert 'current_client_message_id' not in payload
  assert all(set(m)<={'role','content'} for m in payload['conversation'])
  return LLMResult(json.dumps({'decision':'approve','violations':[],'rewrite_instruction':None,'reason':'Consistent','ru_annotations':annotation}),{},0,raw_stop_reason='stop')
 monkeypatch.setattr('runtime.role_adapters.chat',chat)
 class Client:
  def draft(self,payload):return {'message':'The account list is ordered by account ID.'}
 result=SupervisedClientSimulator(reg,Client(),DisclosureSupervisorTransport(RoleConfig())).respond(
  public_task='Account app',candidate_message='How is the list ordered?',approved_history=[{'role':'candidate','content':'earlier','message_id':'secret-id'}],previously_disclosed_hidden_ru_ids=[])
 assert result.text=='The account list is ordered by account ID.'
 assert len(calls)==1 and result.attempts[-1].decision=='approve'
 assert result.attempts[-1].annotation_status=='unavailable'


def test_real_reply_errors_still_require_revision(monkeypatch):
 calls=[]
 def chat(config,system,messages,max_retries):
  calls.append(1)
  return LLMResult(json.dumps({'decision':'revise','violations':['wrong requirement'],'rewrite_instruction':'Correct the threshold.','reason':'Contradicts supplied requirement.','ru_annotations':None}),{},0,raw_stop_reason='stop')
 monkeypatch.setattr('runtime.role_adapters.chat',chat)
 result=DisclosureSupervisorTransport(RoleConfig()).review({'requirement_units':[],'conversation':[]})
 assert result['decision']=='revise' and len(calls)==1

def test_program_counts_followups_once_and_allows_cumulative_correction():
 reg=load_registry(ROOT/'tasks/SWECLAR-013')
 first={'role':'client','message_id':'c1','candidate_message_id':'q1','ru_annotations':rows(reg)}
 second={'role':'client','message_id':'c2','candidate_message_id':'q2','ru_annotations':rows(reg,'partial')}
 s=summarize_annotations(reg,{'messages':[first,first,second]},'clarify')
 assert all(v=={'candidate':2,'client':2,'total':4} for v in s['mention_counts_by_ru'].values())
 assert s['hidden_complete_count']==0 and s['hidden_partial_rate']==1
 missing={'role':'client','message_id':'c0','candidate_message_id':'q0','ru_annotations':None}
 s=summarize_annotations(reg,{'messages':[missing,second]},'clarify')
 assert s['hidden_partial_rate']==1 and s['mention_counts_by_ru'] is None
 assert s['mention_status']=='unavailable' and s['mention_missing_turns']==1
 s=summarize_annotations(reg,{'messages':[first,missing]},'clarify')
 assert s['hidden_complete_rate'] is None and s['status']=='unavailable'

def test_optional_audit_confidence():
 from runtime.audit import validate_audit_output
 reg=load_registry(ROOT/'tasks/SWECLAR-013')
 out=validate_audit_output({'answers':[{'slot_id':u.slot_id,'status':'known','value':'Answer'} for u in reg.slots]},reg)
 assert all(a.confidence is None for a in out.answers)

class Engine:
 def __init__(self,recovers=False):
  self.run={'status':'incomplete','cursor':'completed','evaluation_error':{'code':'evaluator.incomplete','retryable':True},'steps':[]}
  self.repository=self;self.calls=0;self.recovers=recovers
 def get_session(self,sid):return self.run
 def _patch(self,sid,patch):self.run.update(patch)
 def retry(self,sid):
  self.calls+=1
  if self.recovers:self.run.update(status='succeeded',evaluation_error=None)
  return self.run
 def step(self,sid):raise AssertionError('Must not recode for evaluator failures')
@pytest.mark.parametrize('recovers',[False,True])
def test_incomplete_evaluation_retries_without_recoding(recovers):
 e=Engine(recovers);terminal={'succeeded','failed','incomplete'}
 while should_continue(e.run,terminal):advance(e,'id')
 assert e.calls==(1 if recovers else 5)
 assert e.run['status']==('succeeded' if recovers else 'failed')
 assert not should_continue({'status':'succeeded','score':0},terminal)


def test_project_vocabulary_is_not_a_mechanical_veto():
 reg=load_registry(ROOT/'tasks/SWECLAR-013')
 class Client:
  def draft(self,payload):return {'message':'The performance benchmark is optional; sort accounts by account ID.'}
 class Supervisor:
  def review(self,payload):return {'decision':'approve','violations':[],'rewrite_instruction':None,'reason':'Project vocabulary is appropriate.'}
 result=SupervisedClientSimulator(reg,Client(),Supervisor()).respond(public_task='Account app',candidate_message='What about the performance benchmark?',approved_history=[],previously_disclosed_hidden_ru_ids=[])
 assert len(result.attempts)==1 and result.attempts[0].decision=='approve'
