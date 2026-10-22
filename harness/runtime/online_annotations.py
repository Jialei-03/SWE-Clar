"""Model semantic labels; software-owned message association and counting."""
from copy import deepcopy
from typing import Literal
from pydantic import StrictBool
from .models import StrictModel

class RUAnnotation(StrictModel):
    ru_id: str
    status: Literal['none', 'partial', 'complete', 'uncertain']
    agent_mentions_current: StrictBool
    client_mentions_current: StrictBool

def validate_annotations(rows, payload):
    expected = {u['ru_id'] for u in payload['requirement_units']}
    if rows is None or len(rows) != len(expected) or {r.ru_id for r in rows} != expected:
        raise ValueError('Annotation must cover each supplied RU once')
    return rows

def summarize_annotations(registry, dialogue, mode):
    expected={u.slot_id for u in registry.slots}
    hidden={u.slot_id for u in registry.slots if not u.initially_visible}
    base={'protocol':'supervisor.turn_labels.swe-clar','hidden_total':len(hidden)}
    if mode!='clarify':return {**base,'status':'not_applicable'}
    # Internal IDs only: retries/checkpoint projections never create extra counts.
    clients={}
    previous_candidate=None
    for index,m in enumerate(dialogue.get('messages',[])):
        if m.get('role')=='candidate':previous_candidate=m.get('message_id',f'candidate-index-{index}')
        elif m.get('role')=='client':
            clients.setdefault(m.get('message_id',f'client-index-{index}'),(m,m.get('candidate_message_id') or previous_candidate))
    counts={ru:{'candidate':set(),'client':set()} for ru in expected}
    missing_turns=0
    for client_id,(message,candidate_id) in clients.items():
        annotations=message.get('ru_annotations')
        if annotations is None or len(annotations)!=len(expected) or {r['ru_id'] for r in annotations}!=expected:
            missing_turns+=1;continue
        for row in annotations:
            if row['agent_mentions_current'] and candidate_id is not None:counts[row['ru_id']]['candidate'].add(candidate_id)
            if row['client_mentions_current']:counts[row['ru_id']]['client'].add(client_id)
    rows=deepcopy(next(reversed(clients.values()))[0].get('ru_annotations')) if clients else [
        {'ru_id':ru,'status':'none','agent_mentions_current':False,'client_mentions_current':False} for ru in sorted(expected)]
    valid=rows is not None and len(rows)==len(expected) and {r['ru_id'] for r in rows}==expected
    status=('uncertain' if any(r['status']=='uncertain' for r in rows if r['ru_id'] in hidden) else 'complete') if valid else 'unavailable'
    complete=sum(r['ru_id'] in hidden and r['status']=='complete' for r in rows) if valid else None
    partial=sum(r['ru_id'] in hidden and r['status']=='partial' for r in rows) if valid else None
    mention_counts={ru:{'candidate':len(v['candidate']),'client':len(v['client']),'total':len(v['candidate'])+len(v['client'])} for ru,v in counts.items()}
    return {**base,'status':status,'hidden_complete_count':complete,'hidden_partial_count':partial,
        'hidden_complete_rate':complete/len(hidden) if hidden and status=='complete' else None,
        'hidden_partial_rate':partial/len(hidden) if hidden and status=='complete' else None,
        'ru_annotations':rows,'mention_status':'unavailable' if missing_turns else 'complete',
        'mention_counts_by_ru':None if missing_turns else mention_counts,
        'mention_missing_turns':missing_turns,'annotated_client_turns':len(clients)-missing_turns,'approved_client_turns':len(clients)}
