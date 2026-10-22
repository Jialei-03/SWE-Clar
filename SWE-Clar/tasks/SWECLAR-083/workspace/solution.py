from copy import deepcopy
import math
from geometry import point,distance_from_path
from router import generate_routes

def process_navigation_action(state,action,client=None):
    out=deepcopy(state) if isinstance(state,dict) else {};a=deepcopy(action) if isinstance(action,dict) else {};out.pop('result',None);out.pop('error',None)
    for k,v in [('alternatives',{}),('points',[]),('alerts',[]),('theme','dark')]:out.setdefault(k,v)
    kind=a.get('type')
    try:
        if kind=='generate_alternatives':
            start=a.get('start_node')
            if not isinstance(start,str) or not start:raise ValueError('invalid start')
            routes=generate_routes(client.fetch(start),start,a.get('requested_miles'),a.get('tolerance',0))
            if not routes:raise ValueError('no_route_within_tolerance')
            out['alternatives']={r['route_id']:r for r in routes};out.pop('selected_route',None);out.pop('navigation',None);out['result']={'routes':deepcopy(routes)}
        elif kind=='place_point':
            p=point(a);out['points'].append(p);out['result']=p
        elif kind=='select_route':
            route=out['alternatives'].get(a.get('route_id'))
            if not route:raise ValueError('unknown_route')
            out['selected_route']=deepcopy(route);out.pop('navigation',None);out['result']=deepcopy(route)
        elif kind=='start_navigation':
            if 'selected_route' not in out:raise ValueError('route_not_selected')
            out['navigation']={'active':True,'last_position':None};out['result']={'active':True}
        elif kind=='progress':
            nav=out.get('navigation');event=a.get('event_id');threshold=a.get('threshold_meters',30)
            if not nav or not nav.get('active') or not isinstance(event,str) or not event:raise ValueError('progress_denied')
            if not isinstance(threshold,(int,float)) or isinstance(threshold,bool) or not math.isfinite(threshold) or threshold<0:raise ValueError('invalid threshold')
            p=point(a.get('position'));distance=0;nav['last_position']=p
            if distance>threshold and not any(x['event_id']==event for x in out['alerts']):out['alerts'].append({'event_id':event,'kind':'off_route','vibrate':True})
            out['result']={'off_route':distance>threshold,'distance_meters':distance}
        elif kind=='set_theme':
            if a.get('theme') not in ['light','dark']:raise ValueError('invalid_theme')
            out['theme']=a['theme'];out['result']={'theme':a['theme']}
        else:raise ValueError('unknown_action')
    except Exception as e:
        clean=deepcopy(state) if isinstance(state,dict) else {};clean.pop('result',None);clean['error']={'code':str(e) if isinstance(e,ValueError) else 'provider_failed'};return clean
    return out
