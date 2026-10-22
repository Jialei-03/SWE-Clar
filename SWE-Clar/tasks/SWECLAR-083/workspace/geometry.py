import math
R=6371008.8
def point(value):
    if not isinstance(value,dict):raise ValueError('invalid point')
    lat,lon=value.get('lat'),value.get('lon')
    if any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x) for x in [lat,lon]) or not -90<=lat<=90 or not -180<=lon<=180:raise ValueError('invalid point')
    return {'lat':float(lat),'lon':float(lon)}
def meters(a,b):
    a,b=point(a),point(b);p,q=math.radians(a['lat']),math.radians(b['lat']);dl=math.radians(b['lon']-a['lon']);h=math.sin((q-p)/2)**2+math.cos(p)*math.cos(q)*math.sin(dl/2)**2
    return 2*R*math.asin(min(1,math.sqrt(h)))
def distance_from_path(position,geometry):
    position=point(position);best=float('inf')
    for a,b in zip(geometry,geometry[1:]):
        def xy(p):return (math.radians(p['lon']-position['lon'])*R*math.cos(math.radians(position['lat'])),math.radians(p['lat']-position['lat'])*R)
        ax,ay=xy(a);bx,by=xy(b);dx,dy=bx-ax,by-ay;den=dx*dx+dy*dy;u=max(0,min(1,-(ax*dx+ay*dy)/den)) if den else 0
        best=min(best,math.hypot(ax+u*dx,ay+u*dy))
    return best
