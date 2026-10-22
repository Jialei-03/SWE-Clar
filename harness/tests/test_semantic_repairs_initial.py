"""Focused controls for repaired contracts, not full candidate qualification."""
import ast
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / 'SWE-Clar/tasks'

def function_from_source(task, filename, name, namespace):
    source = TASKS / task / 'evaluation/tests' / filename
    tree = ast.parse(source.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace[name]

def test_045_setup_satisfies_required_entity_names():
    seen = []
    def strict_call(state, action):
        if action['type'] in {'register_terminal', 'create_customer'}:
            assert isinstance(action['name'], str) and action['name']
        seen.append(action)
        return state
    setup = function_from_source('SWECLAR-045', 'boundaries.py', 'setup', {'call': strict_call})
    setup()
    assert len(seen) == 4

def test_045_rejection_assertion_detects_cross_card_balance_mutation():
    state = {'cards': {'c': {'balance': 0.2}, 'other-card': {'balance': 0}}, 'pending': {'t': []}}
    action = {'type': 'refund', 'card_id': 'other-card', 'sale_event_id': 'two', 'amount': 0.1}
    correct = function_from_source('SWECLAR-045', 'boundaries.py', 'rejected',
                                   {'call': lambda s, a: {**s, 'error': {'code': 'wrong_card'}}})
    correct(state, action)
    wrong = function_from_source('SWECLAR-045', 'boundaries.py', 'rejected',
                                 {'call': lambda s, a: {**s, 'cards': {**s['cards'], 'other-card': {'balance': 0.1}}}})
    with pytest.raises(AssertionError):
        wrong(state, action)

def test_053_interface_distinguishes_active_and_display_sets():
    registry = yaml.safe_load((TASKS / 'SWECLAR-053/evaluation/requirement_units.yaml').read_text())
    unit = next(u for u in registry['requirement_units'] if u['ru_id'] == 'RU-003')
    meaning = unit['test_interface']['output']['meaning']
    assert 'active set' in meaning and 'Earlier broken' in meaning
    assert 'hide_broken_levels is false' in meaning
    assert 'replaced records are never displayable' in meaning

def test_087_error_key_declared_in_every_interface():
    import json
    task = TASKS / 'SWECLAR-087'
    registry = yaml.safe_load((task / 'evaluation/requirement_units.yaml').read_text())
    for unit in registry['requirement_units']:
        record = unit['test_interface']['output']['error_record']
        assert set(record['required_fields']) == {'workbook', 'stage', 'error'}
        assert record['additional_properties'] is True
    public = json.loads((task / 'evaluation/project/DELIVERY_INTERFACE.json').read_text())
    assert 'exact fields workbook, stage and error' in public['readme']
    assert all('error_record' in i['output'] for i in public['interfaces'])
