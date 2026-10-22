"""Room creation baseline; complete participant, turn and audio behavior."""
from copy import deepcopy
import math


def process_voice_event(state: dict, event: dict) -> dict:
    out = deepcopy(state)
    out.setdefault('rooms', {})
    out.pop('error', None)
    out.pop('result', None)
    if event.get('type') == 'create_room':
        room_id = event.get('room_id')
        limit = event.get('turn_limit')
        private = event.get('private', False)
        token = event.get('access_token', '')
        valid = (event.get('admin_id') in out.get('admins', [])
                 and isinstance(room_id, str) and bool(room_id.strip())
                 and room_id not in out['rooms'] and isinstance(private, bool)
                 and isinstance(limit, (int, float)) and not isinstance(limit, bool)
                 and math.isfinite(limit) and limit > 0
                 and (not private or isinstance(token, str) and bool(token)))
        if not valid:
            out['error'] = {'code': 'invalid_room'}
            return out
        out['rooms'][room_id] = {'private': private, 'access_token': token,
                                 'turn_limit': limit, 'participants': [],
                                 'locked': [], 'current': None, 'deadline': None}
        out['result'] = {'room_id': room_id}
    else:
        out['error'] = {'code': 'not_implemented'}
    return out
