"""Actual evaluator protocol controls, not candidate correctness controls.

Execute the real result parser/wrapper against synthetic worker outputs. No
candidate or Docker process is launched; behavioral test semantics are separate.
"""
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

TASKS=sorted((Path(__file__).resolve().parents[2]/'SWE-Clar/tasks').iterdir())

@pytest.mark.parametrize('task',TASKS,ids=lambda p:p.name)
@pytest.mark.parametrize('variant',['pass','fail','missing','duplicate','non_boolean','infrastructure'])
def test_evaluator_result_protocol(task,variant,tmp_path,monkeypatch):
    p=task/'evaluation/tests/official_verifier.py'
    expected=json.loads((p.parent/'expected_gates.json').read_text())['expected_gate_ids']
    results=[{'ru_id':gate.removesuffix('-T01'),'passed':variant!='fail'} for gate in expected]
    if variant=='missing':results.pop()
    if variant=='duplicate':results[-1]=results[0]
    if variant=='non_boolean':results[0]['passed']='true'
    payload={'harness_ok':variant!='infrastructure','results':results}
    tree=ast.parse(p.read_text())
    parser=next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='structured_gate_result'),None)
    if parser is not None:
        gates=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                   and any(isinstance(t,ast.Name) and t.id=='GATES' for t in n.targets))
        namespace={'json':json,'GATES':gates}
        exec(compile(ast.Module(body=[parser],type_ignores=[]),str(p),'exec'),namespace)
        actual=namespace['structured_gate_result'](json.dumps(payload),expected[0].removesuffix('-T01'))
    else:
        spec=importlib.util.spec_from_file_location('isolated_verifier_'+task.name,p)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        # The wrapper launches only its worker, which this fixture replaces.
        monkeypatch.setattr(module.subprocess,'run',lambda *a,**kw:SimpleNamespace(
            returncode=0,stdout=json.dumps(payload),stderr=''))
        monkeypatch.setenv('SWECLAR_LOG_DIR',str(tmp_path))
        module.main()
        report=json.loads((tmp_path/'gates.json').read_text())
        actual={'harness_ok':report['harness_ok'],'passed':all(g['verdict'] for g in report['gates'])}
    assert actual is not None
    if variant in {'pass','fail'}:
        assert actual['harness_ok'] is True
        assert actual['passed'] is (variant=='pass')
    else:
        assert actual['harness_ok'] is False
        assert actual['passed'] is False
