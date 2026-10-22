import importlib.util
import json
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[2] / 'SWE-Clar/environments/prepare_task.py'
    spec = importlib.util.spec_from_file_location('prepare_task_compat', path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_inspect_uses_legacy_compatible_command(monkeypatch):
    m = module()
    def output(command):
        assert command == ['docker', 'image', 'inspect', 'sha256:pinned']
        return json.dumps([{'Os': 'linux', 'Architecture': 'amd64'}])
    monkeypatch.setattr(m, 'output', output)
    assert m.inspect_image('sha256:pinned', 'linux/amd64')['Architecture'] == 'amd64'


@pytest.mark.parametrize('platform', ['linux/arm64', 'windows/amd64', 'linux/amd64/v3'])
def test_inspect_rejects_wrong_platform(monkeypatch, platform):
    m = module()
    monkeypatch.setattr(m, 'output', lambda command: json.dumps([{'Os': 'linux', 'Architecture': 'amd64'}]))
    with pytest.raises(SystemExit, match='mismatch'):
        m.inspect_image('sha256:pinned', platform)
