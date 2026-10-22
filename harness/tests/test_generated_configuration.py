"""Generated provider profiles must satisfy the runtime contract before API calls."""
import importlib.util
from pathlib import Path
import pytest
from runtime.composition import _runtime_safe_pi_profile_snapshot
from llm import RoleConfig

@pytest.mark.parametrize('style', ['chat', 'responses', 'claude'])
def test_generated_configuration_supports_runtime_snapshots(style):
    source = Path(__file__).resolve().parents[2] / 'tools' / 'configure_model.py'
    spec = importlib.util.spec_from_file_location('configure_model', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = module.configuration(style, 'https://provider.example/v1', 'example-model')
    snapshot = _runtime_safe_pi_profile_snapshot(config['candidate'], role='candidate')
    assert snapshot['label'] == 'example-model'
    assert snapshot['model'] == 'example-model'
    assert 'api_key' not in config['candidate']
    for role in ('client', 'supervisor', 'judge'):
        assert RoleConfig.from_profile(config[role]).model == 'example-model'
        snapshot = _runtime_safe_pi_profile_snapshot(config[role]['pi_profile'], role=role)
        assert snapshot['label'] == 'example-model'
