"""Independent supervision config and explicit key routing, without API calls."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from llm import LLMError,RoleConfig
from runtime import composition,pi_adapters,task_runtime

ROOT=Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('separate',[False,True])
def test_supervisor_does_not_replace_audit_judge(tmp_path,monkeypatch,separate):
    # Compose real adapters; skip only unavailable local image provenance.
    class Runtime:
        workspace_path='/workspace'
        def provenance(self):return {}
    monkeypatch.setattr(task_runtime,'load_task_runtime',lambda *a,**k:Runtime())
    luna=RoleConfig(model='gpt-5.6-luna')
    glm=RoleConfig(model='accounts/fireworks/models/glm-5p3-flash')
    profile={'model':'gpt-5.6-luna','profile_id':'test-luna','label':'Luna','provider':'openai'}
    engine,snapshot,adapters=composition.build_engine('SWECLAR-001',tasks_dir=ROOT/'SWE-Clar/tasks',state_dir=tmp_path,profile=profile,client_config=luna,judge_config=luna,supervisor_config=glm if separate else None)
    assert snapshot['audit_judge']['model']=='gpt-5.6-luna'
    assert snapshot['disclosure_supervisor']['model']==(glm.model if separate else luna.model)
    assert snapshot['disclosure_supervisor']['source_role']==('supervisor' if separate else 'judge')

def test_explicit_pi_key_missing_does_not_fallback(monkeypatch):
    monkeypatch.delenv('TEST_EXPLICIT_MODEL_KEY',raising=False)
    monkeypatch.setenv('MINIMAX_API_KEY','unrelated')
    with pytest.raises(LLMError,match='credential environment'):
        pi_adapters._run_pi_text({'api_key_env':'TEST_EXPLICIT_MODEL_KEY'},system_prompt='x',user_payload={})

def test_explicit_pi_key_is_in_process_env_not_payload(monkeypatch):
    monkeypatch.setenv('TEST_EXPLICIT_MODEL_KEY','synthetic-secret')
    def run(*args,**kwargs):
        assert kwargs['env']['SWECLAR_PI_MODEL_API_KEY']=='synthetic-secret'
        assert 'synthetic-secret' not in kwargs['input']
        return SimpleNamespace(returncode=0,stdout=json.dumps({'kind':'pi_result','result':{'ok':True,'text':'OK'}}),stderr='')
    monkeypatch.setattr(pi_adapters.subprocess,'run',run)
    pi_adapters._run_pi_text({'api_key_env':'TEST_EXPLICIT_MODEL_KEY'},system_prompt='x',user_payload={})
