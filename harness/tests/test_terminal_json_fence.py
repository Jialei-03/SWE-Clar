import pytest
from llm import extract_json

def test_prose_brackets_do_not_override_explicit_terminal_response():
    assert extract_json('Check [a,b] and {example:1}.```json\n{"decision":"approve"}\n```', expected_type=dict) == {'decision': 'approve'}

@pytest.mark.parametrize('text', [
    '```json\n{"outer": [1,2]',
    '{"outer":\n```json\n{"decision":"approve"}\n```',
    'Prose```json\n{"decision":\n```',
    'Prose```json\n{}\n``` then ```json\n{}\n```',
    'Prose```json\n{}\n``` trailing contradictory prose',
    'Prose```json\n[]\n```',
])
def test_ambiguous_truncated_or_wrong_type_is_rejected(text):
    with pytest.raises(ValueError):
        extract_json(text, expected_type=dict)
