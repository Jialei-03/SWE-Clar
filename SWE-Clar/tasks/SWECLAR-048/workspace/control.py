"""Application policy; capture formats and deployment details live elsewhere."""
import copy


class ControlError(ValueError):pass


def initial(settings=None):
    state={'devices':[],'selected':None,'resolution':'640x480','zoom':1,'display_input':'preview','kiosk':False,'last_action':None}
    if settings:state.update(settings)
    return state


def discovery(state, devices):
    result=copy.deepcopy(state);result['devices']=devices
    if result['selected'] not in {x['id'] for x in devices}:
        preferred=sorted(x['id'] for x in devices if x['preferred'])
        result['selected']=devices[0]['id'] if devices else None
    return result


def command(state, event):
    if not isinstance(event,dict):raise ControlError('invalid_event')
    result=copy.deepcopy(state);kind=event.get('type')
    if kind=='resolution':
        if event.get('value') not in ('640x480','1280x720','1920x1080'):raise ControlError('invalid_resolution')
        result['resolution']=event['value']
    elif kind=='device':
        if event.get('id') not in {x['id'] for x in state['devices']}:raise ControlError('missing_device')
        result['selected']=event['id']
    elif kind=='display':
        if event.get('value') not in ('preview','auxiliary'):raise ControlError('invalid_input')
        result['display_input']=event['value']
    elif kind in ('key','controller'):
        raise ControlError('controls_not_implemented')
    else:raise ControlError('invalid_event')
    return result
