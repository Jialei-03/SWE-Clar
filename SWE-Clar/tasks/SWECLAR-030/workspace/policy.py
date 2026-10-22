"""Family policy operations; all example identities are synthetic."""
from copy import deepcopy


def process_control_action(state, action):
    state = deepcopy(state)
    state.pop('result', None)
    state.pop('error', None)
    for key, default in [('users', {}), ('devices', {}), ('policies', {}),
                         ('activity', []), ('notifications', []), ('audit', [])]:
        state.setdefault(key, default)
    def error(code):
        state['error'] = {'code': code}
        return state
    kind = action.get('type')
    if kind == 'configure_mode':
        user = action.get('user_id')
        device = action.get('device_id')
        mode = action.get('mode')
        if user not in state['users'] or not isinstance(device, str) or not device or device in state['devices']:
            return error('link_denied')
        if mode == 'self':
            state['devices'][device] = {'owner_id': user, 'mode': mode}
        elif mode == 'parent_child':
            child = action.get('child_id')
            record = state['users'].get(child, {})
            if (state['users'][user].get('role') != 'parent' or record.get('role') != 'child'
                    or record.get('parent_id') != user
                    or any(d.get('owner_id') == child for d in state['devices'].values())):
                return error('link_denied')
            state['devices'][device] = {'owner_id': child, 'parent_id': user, 'mode': mode}
        else:
            return error('link_denied')
        state['result'] = {'device_id': device}
        return state
    # Complete policy, access, report and deletion operations here.
    return error('unsupported_action')
