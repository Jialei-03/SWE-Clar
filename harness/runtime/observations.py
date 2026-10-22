"""Project only the candidate's own observable pre-freeze history.

Never copy researcher diagnostics, Client drafts, supervisor requests or private
RU annotations. Keep each Pi turn's assistant and tool messages once, without
recursively copying its user request (which contains previous turns).
"""
from copy import deepcopy

TEXT_HISTORY_VERSION = 'observable-history-no-private-reasoning-v2'


def textual_observations(observations):
    """Copy history for JSON prompt text, never for native provider replay.

    Private provider reasoning is not ordinary observable conversation text.
    Native provider replay and archived source remain unchanged. Preserve all
    task text and tool data, including similarly named application fields.
    """
    cleaned = deepcopy(observations)

    def clean_assistant(message):
        if not isinstance(message, dict):
            return
        content = message.get('content')
        if isinstance(content, list):
            message['content'] = [part for part in content if not (
                isinstance(part, dict) and part.get('type') in
                {'thinking', 'redacted_thinking', 'reasoning'})]
        # Compacted assistantSummary records hold reasoning outside content.
        for key in ('thinking', 'reasoning', 'thinkingSignature'):
            message.pop(key, None)

    for observation in cleaned:
        for message in observation.get('messages', []):
            if message.get('role') == 'assistant':
                clean_assistant(message)
        # Compacted turns are another copy of assistant history, not tool data.
        for turn in observation.get('pre_compaction_turns', []):
            clean_assistant(turn.get('assistant'))
    return cleaned


def candidate_observations(messages):
    turns=[]
    for message in messages:
        if message.get('role')!='candidate':
            continue
        trace=message.get('model_trace') or {}
        visible=[deepcopy(m) for m in trace.get('messages',[]) if m.get('role') in ('assistant','toolResult','tool')]
        # Pi can compact session.messages. Its turn log retains the earlier
        # assistant text/thinking and tool results; restore only missing turns
        # so a complete current message is not repeated in the Audit context.
        visible_timestamps={m.get('timestamp') for m in visible if m.get('role')=='assistant' and m.get('timestamp') is not None}
        prior_turns=[deepcopy(t) for t in trace.get('turns',[]) if
                     (t.get('assistant') or {}).get('timestamp') not in visible_timestamps]
        if visible or prior_turns or trace.get('tool_events'):
            turns.append({'dialogue_message_id':message.get('message_id'),
                          'messages':visible,'pre_compaction_turns':prior_turns,
                          'tool_events':deepcopy(trace.get('tool_events',[]))})
    return textual_observations(turns)
