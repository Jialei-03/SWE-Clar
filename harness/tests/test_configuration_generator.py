import importlib.util
from pathlib import Path
import pytest

path = Path(__file__).resolve().parents[2] / 'tools/configure_model.py'
spec = importlib.util.spec_from_file_location('configuration_generator', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

@pytest.mark.parametrize('style,api', list(module.APIS.items()))
def test_four_roles_keep_api_and_env(style, api):
    config = module.configuration(style, 'https://example.invalid/v1', 'test-model', 'PRIVATE_TOKEN')
    profiles = [config['candidate']] + [config[r]['pi_profile'] for r in ['client','supervisor','judge']]
    assert all(p['api'] == api and p['api_key_env'] == 'PRIVATE_TOKEN' and 'api_key' not in p for p in profiles)

def test_plain_http_rejected():
    with pytest.raises(ValueError):
        module.configuration('chat', 'http://example.invalid', 'test-model')
