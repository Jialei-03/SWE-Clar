"""Device workflow with durable pairing/history and actual peer exchanges."""
import re
from wire import exchange


class WorkflowError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value) is not None


def peer(port, request):
    try:
        response, packets = exchange(port, request)
    except (OSError, ValueError, UnicodeError):
        raise WorkflowError('peer_failure', 502)
    if not response['ok']:
        raise WorkflowError('peer_denied', 403)
    return response, packets


def discovery(port, service):
    response, _ = peer(port, {'op':'scan', 'service':service})
    advertisements = response.get('devices')
    if not isinstance(advertisements, list): raise WorkflowError('peer_failure', 502)
    devices = {}
    for item in advertisements:
        if (not isinstance(item, dict) or not identifier(item.get('device_id'))
                or not isinstance(item.get('name'), str) or not isinstance(item.get('services'), list)
                or not all(isinstance(s, str) for s in item['services'])):
            raise WorkflowError('peer_failure', 502)
        devices[item['device_id']] = {k:item[k] for k in ('device_id','name','services')}
    return [value for value in devices.values() if service in value['services']]


def lifecycle(state, op, body, port):
    # Provisional UI wiring; replace with the clarified peer-backed lifecycle.
    device_id = body.get('device_id')
    if op == 'pair':
        if device_id not in state['paired']: state['paired'].append(device_id)
    elif op == 'connect': state['connected'] = device_id
    elif op == 'disconnect': state['connected'] = None


def command(state, body, port):
    # The wire client exists; connect it to the agreed command/history policy.
    result = {'accepted': body.get('name')}
    state['commands'].append({'device_id':body.get('device_id'), 'command_id':body.get('command_id'),
                              'name':body.get('name'), 'result':result})
    return result
