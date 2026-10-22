"""Browser helpers remain executable when extracted from a portable archive."""
import importlib.util
from pathlib import Path
import pytest

def prepare_module():
    source = Path(__file__).resolve().parents[2] / 'SWE-Clar/environments/prepare_task.py'
    spec = importlib.util.spec_from_file_location('prepare_task', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_launcher_mode_restored_without_changing_source(tmp_path):
    launcher = tmp_path / 'browser_launcher.py'
    body = b'#!/usr/bin/env python3\nprint("launcher")\n'
    launcher.write_bytes(body)
    launcher.chmod(0o644)
    ordinary = tmp_path / 'test_gate.py'
    ordinary.write_text('pass\n')
    ordinary.chmod(0o644)
    prepare_module().normalize_support_permissions(tmp_path)
    assert launcher.stat().st_mode & 0o777 == 0o755
    assert launcher.read_bytes() == body
    assert ordinary.stat().st_mode & 0o777 == 0o644

def test_launcher_without_shebang_rejected(tmp_path):
    (tmp_path / 'browser_launcher.py').write_text('pass\n')
    with pytest.raises(ValueError, match='shebang'):
        prepare_module().normalize_support_permissions(tmp_path)
