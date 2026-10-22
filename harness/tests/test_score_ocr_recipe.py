"""Frozen dependency wiring only; real OCR is exercised by image preflight."""
import ast
import hashlib
import json
from pathlib import Path
import shutil

import pytest

ENV = Path(__file__).resolve().parents[2] / 'SWE-Clar/environments'

def test_ocr_lock_reuses_verified_vision_packages_and_preflight():
    score = json.loads((ENV / 'amd64/python-media-score/lock.json').read_text())
    vision = json.loads((ENV / 'amd64/python-vision/lock.json').read_text())
    assert score['ocr_deb_packages'] == vision['deb_packages']
    names = [row['filename'] for row in score['ocr_deb_packages']]
    assert any(n.startswith('tesseract-ocr_') for n in names)
    assert any(n.startswith('tesseract-ocr-eng_') for n in names)
    assert all(len(row['sha256']) == 64 and row['url'].startswith('https://') for row in score['ocr_deb_packages'])
    docker = (ENV / 'amd64/python-media-score/Dockerfile').read_text()
    assert 'COPY ocr-packages /tmp/ocr-packages' in docker
    assert 'dpkg -i /tmp/ocr-packages/*.deb' in docker
    health = (ENV / 'amd64/python-media-score/score_health.py').read_text()
    assert "'tesseract','stdin','stdout','-l','eng'" in health
    assert "{'C4','E4','G4','C5'}" in health

def test_actual_ocr_staging_uses_verified_obtainer(tmp_path):
    path = ENV / 'frozen_extensions.py'
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'stage_ocr_packages')
    namespace = {'Path':Path, 'shutil':shutil}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
    source = tmp_path / 'cached-verified-package'
    source.write_bytes(b'synthetic package')
    row = {'filename':'test_amd64.deb','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    seen=[]
    def obtain(record):
        seen.append(record)
        assert hashlib.sha256(source.read_bytes()).hexdigest()==record['sha256']
        return source
    namespace['stage_ocr_packages'](tmp_path,{'ocr_deb_packages':[row]},obtain)
    assert seen==[row] and (tmp_path / 'ocr-packages/test_amd64.deb').read_bytes()==source.read_bytes()
    with pytest.raises(ValueError,match='basename'):
        namespace['stage_ocr_packages'](tmp_path,{'ocr_deb_packages':[{**row,'filename':'../escape'}]},obtain)
