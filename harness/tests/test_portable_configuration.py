"""No real service or credential is used by these tests."""
from pathlib import Path
from types import SimpleNamespace
import json,pytest
from llm import RoleConfig
from runtime.tiered_audit import TieredAuditJudge
from runtime.tiered_audit import validate_request_settings

@pytest.mark.parametrize('api',['openai-completions','openai-responses','anthropic-messages'])
def test_judge_settings_are_protocol_independent(api):
    profile={'model':'test','api':api,'reasoning':True,'thinking':'max'}
    validate_request_settings([{'model':'test','api':api,'thinking_level':'high'}],profile)
    with pytest.raises(ValueError):
        validate_request_settings([{'model':'test','api':api,'thinking_level':'low'}],profile)

def test_legacy_max_record_remains_valid():
    validate_request_settings([{'model':'test','reasoning':{'effort':'max'}}],{'model':'test'})

@pytest.mark.parametrize('name',['CUSTOM_MODEL_TOKEN','ANOTHER_VALID_ENV_NAME'])
def test_any_declared_credential_variable(name,tmp_path):
    config=SimpleNamespace(pi_profile={'model':'user-selected-model','thinking':'max','api_key_env':name})
    judge=TieredAuditJudge(config,task_root=tmp_path,registry=None,cache_dir=tmp_path/'cache')
    assert judge.model=='user-selected-model'

def test_example_contains_placeholders_not_secret_values():
    d=json.loads((Path(__file__).resolve().parents[1]/'config.example.json').read_text())
    for profile in [d['candidate'],*[d[x]['pi_profile'] for x in ['client','judge','supervisor']]]:
        assert 'api_key' not in profile
        assert profile['base_url']=='https://api.example.invalid/v1'
        assert profile['api_key_env']=='SWECLAR_API_KEY'
