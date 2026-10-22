from copy import deepcopy

import pytest

from runtime.artifacts import ArtifactStore
from runtime.freeze import freeze_context, model_visible_frozen_context
from runtime.observations import candidate_observations, textual_observations


def history():
    return [{'messages': [
        {'role': 'assistant', 'content': [
            {'type': 'thinking', 'thinking': 'Keep reasoning', 'thinkingSignature': 'opaque'},
            {'type': 'text', 'text': 'Keep text'},
            {'type': 'toolCall', 'arguments': {'thinkingSignature': 'business data'}},
        ]},
        {'role': 'toolResult', 'content': [{'type': 'thinking', 'thinkingSignature': 'tool data'}]},
        {'role': 'user', 'content': [{'type': 'thinking', 'thinkingSignature': 'user data'}]},
        {'role': 'assistant', 'content': 'Plain text'},
    ], 'pre_compaction_turns': [{
        'assistant': {'content': [{'type': 'thinking', 'thinking': 'Earlier reasoning', 'thinkingSignature': 'old opaque'}]},
        'tool_results': [{'thinkingSignature': 'Keep tool result'}],
    }]}]


def test_only_provider_fields_removed_without_mutation():
    original = history()
    snapshot = deepcopy(original)
    expected = deepcopy(original)
    del expected[0]['messages'][0]['content'][0]
    del expected[0]['pre_compaction_turns'][0]['assistant']['content'][0]
    cleaned = textual_observations(original)
    assert cleaned == expected
    assert original == snapshot
    assert textual_observations(cleaned) == cleaned


def test_candidate_public_entry_preserves_native_trace():
    observations = history()[0]
    trace = {'messages': observations['messages'], 'turns': observations['pre_compaction_turns']}
    messages = [{'role': 'candidate', 'message_id': 'q', 'model_trace': trace}]
    before = deepcopy(messages)
    result = candidate_observations(messages)
    assert 'thinkingSignature' not in result[0]['messages'][0]['content'][0]
    assert result[0]['pre_compaction_turns'][0]['assistant']['content'] == []
    assert messages == before


@pytest.mark.parametrize('mode', ['clarify', 'direct', 'oracle'])
def test_freeze_cleans_once_for_shared_audit_coding_prefix(tmp_path, mode):
    original = history()
    snapshot = deepcopy(original)
    frozen = freeze_context(
        task_id='t', question_atom_limit=None, public_task='Job', messages=[],
        exposure_ledger=[], source_catalog=[], attachments=[],
        candidate_config_digest='sha256:' + '0' * 64,
        artifacts=ArtifactStore(tmp_path), benchmark_mode=mode,
        candidate_observation_history=original,
    )
    expected = textual_observations(original)
    assert frozen.evidence['candidate_observations'] == expected
    assert model_visible_frozen_context(frozen)['evidence']['candidate_observations'] == expected
    assert original == snapshot


def test_empty_history():
    assert textual_observations([]) == []


def test_new_freeze_digest_ignores_only_wire_signature(tmp_path):
    def freeze(observations):
        return freeze_context(
            task_id='t', question_atom_limit=None, public_task='Job', messages=[],
            exposure_ledger=[], source_catalog=[], attachments=[],
            candidate_config_digest='sha256:' + '0' * 64,
            artifacts=ArtifactStore(tmp_path), candidate_observation_history=observations,
        )
    original = history()
    changed = deepcopy(original)
    changed[0]['messages'][0]['content'][0]['thinkingSignature'] = 'different wire state'
    assert freeze(original).prefix_digest == freeze(changed).prefix_digest
    changed[0]['messages'][0]['content'][0]['thinking'] = 'Different readable reasoning'
    assert freeze(original).prefix_digest == freeze(changed).prefix_digest

def test_compacted_reasoning_removed_but_tool_business_data_preserved():
    original=[{'messages': [], 'pre_compaction_turns': [{'assistant': {
        'thinking':'private', 'text':'Question', 'tool_calls':[{'arguments':{'thinking':'business'}}]},
        'tool_results':[{'thinking':'tool data'}]}]}]
    cleaned=textual_observations(original)
    turn=cleaned[0]['pre_compaction_turns'][0]
    assert 'thinking' not in turn['assistant']
    assert turn['assistant']['text']=='Question'
    assert turn['assistant']['tool_calls'][0]['arguments']['thinking']=='business'
    assert turn['tool_results']==[{'thinking':'tool data'}]
    assert original[0]['pre_compaction_turns'][0]['assistant']['thinking']=='private'
