"""Playable arena transport is supplied; implement the gameplay operations."""
from copy import deepcopy

def process_game_action(state: dict, action: dict) -> dict:
    out = deepcopy(state)
    out.pop('result', None)
    out['error'] = {'code': 'not_implemented'}
    return out
