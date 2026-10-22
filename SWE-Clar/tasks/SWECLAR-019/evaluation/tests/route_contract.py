"""Private behavioral gates for the frozen route workspace contract."""
import base64
import concurrent.futures
from io import BytesIO
import json
import sys
import traceback
from urllib.parse import quote
sys.path.insert(0, '/public_tests')
from PIL import Image, PngImagePlugin
from playwright.sync_api import expect, TimeoutError as BrowserTimeout, Error as BrowserError
from route_support import Application, CandidateFailure, browser_session, request
from test_public import run as public_run
from fixtures import sample_png


class Checks:
    def __init__(self): self.passed = []
    def require(self, value, name):
        if not value: raise CandidateFailure(name)
        self.passed.append(name)


def enc(value): return quote(value, safe='')
def api(c, app, path, body=None, token=None, method=None, status=200):
    result = request(app, path, body, token, method)
    c.require(result['status'] == status, f'{path}: expected {status}, received {result["status"]}')
    return result['body']
def tokens(c, app):
    return {u['id']: api(c, app, '/api/login', {'username': u['username'], 'password': u['password']})['token'] for u in app.seed['users']}
def complete(c, app, token, name='Synthetic member'):
    image = api(c, app, '/api/assets', {'png_base64': base64.b64encode(sample_png()).decode()}, token, status=201)['asset']
    api(c, app, '/api/profile', {'name': name, 'photo_id': image['id']}, token, 'PUT')
    return image
def point(c, app, token, name, lat=12, lon=20, photos=None):
    return api(c, app, '/api/waypoints', {'name': name, 'lat': lat, 'lon': lon, 'photo_ids': photos or []}, token, status=201)['waypoint']
def route(c, app, token, title, ids):
    return api(c, app, '/api/routes', {'title': title, 'waypoint_ids': ids}, token, status=201)['route']
def pin(c, app, token, item, value=True):
    return api(c, app, '/api/routes/' + enc(item['id']) + '/pin', {'pinned': value}, token, 'PUT')['route']
def setup(c, app):
    t = tokens(c, app)
    for key in ['member-a', 'member-b']: complete(c, app, t[key], 'Synthetic ' + key)
    photo = api(c, app, '/api/assets', token=t['member-a'])['assets'][0]['id']
    points = [point(c, app, t['member-a'], 'First synthetic stop', photos=[photo]), point(c, app, t['member-a'], 'Second synthetic stop', -14, 27)]
    return t, points, [p['id'] for p in points]
def page_login(page, app, key='member-a'):
    u = next(u for u in app.seed['users'] if u['id'] == key)
    page.goto(app.url); page.locator('#username').fill(u['username']); page.locator('#password').fill(u['password']); page.locator('#login').click()
    expect(page.locator('#workspace')).to_be_visible()
def wp_path(item): return '/api/waypoints/' + enc(item['id'])
def fields(row, names): return {name: row[name] for name in names}
WP = ('id', 'owner_id', 'name', 'lat', 'lon', 'photo_ids', 'revision')


def hold_first(page, pattern):
    held = []; page.evaluate('window.benchmarkHeld=0')
    def hold(route):
        if held: route.continue_(); return
        held.append((route, route.fetch())); page.evaluate('window.benchmarkHeld++')
    page.route(pattern, hold); return held, hold


def release(held):
    route, response = held[0]
    try: route.fulfill(response=response)
    except BrowserError:
        if route.request.failure is None: raise


def forbid_unrequested_route(page, title):
    # Observe forbidden visible state without patching candidate classes or assuming an event strategy.
    try:
        page.wait_for_function('(title)=>document.getElementById("route-heading").textContent.includes(title)', arg=title, timeout=1500)
    except BrowserTimeout:
        return
    raise CandidateFailure('Pin action opened an unrequested route')


def map_matches(page, points):
    page.wait_for_function('''(points) => {
      const svg = document.getElementById('map');
      if (!svg || !svg.getScreenCTM()) return false;
      const inverse = svg.getScreenCTM().inverse();
      return points.every(point => [...svg.querySelectorAll('[data-waypoint-id]')]
        .filter(marker => marker.dataset.waypointId === point.id)
        .some(marker => [marker, ...marker.querySelectorAll('*')].some(shape => {
          if (!shape.getBBox || !shape.getScreenCTM || ['text','tspan'].includes(shape.tagName)) return false;
          if (!shape.getClientRects().length) return false;
          const box=shape.getBBox(), transform=shape.getScreenCTM(); if (!transform) return false;
          const center=new DOMPoint(box.x+box.width/2,box.y+box.height/2).matrixTransform(transform).matrixTransform(inverse);
          return Math.abs(center.x-2*(point.lon+180))<0.1 && Math.abs(center.y-2*(85-point.lat))<0.1;
        })));
    }''', arg=points)
    page.wait_for_function(ROUTE_INK, arg=points)


ROUTE_INK = r'''(points) => {
 const svg=document.getElementById('map');if(!svg?.getScreenCTM())return false;
 const shapes=[...svg.querySelectorAll('*')].filter(s=>{
   if(!s.isPointInStroke||s.closest('[data-waypoint-id]')||!s.getScreenCTM())return false;
   for(let n=s;n&&n!==svg.parentElement;n=n.parentElement){const c=getComputedStyle(n);if(c.display==='none'||c.visibility==='hidden'||Number(c.opacity)===0)return false;}
   return s.getClientRects().length>0;
 });
 const coords=points.map(p=>[2*(p.lon+180),2*(85-p.lat)]);
 return coords.slice(1).every((b,i)=>{
   const a=coords[i],length=Math.hypot(b[0]-a[0],b[1]-a[1]);
   for(let d=10;d<length-10;d+=2){
     const screen=new DOMPoint(a[0]+(b[0]-a[0])*d/length,a[1]+(b[1]-a[1])*d/length).matrixTransform(svg.getScreenCTM());
     if(!shapes.some(s=>{const inverse=s.getScreenCTM().inverse(),p=screen.matrixTransform(inverse),c=getComputedStyle(s);
       if(c.stroke!=='none'&&Number(c.strokeOpacity)>0&&s.isPointInStroke(p))return true;
       if(c.fill==='none'||Number(c.fillOpacity)===0||!s.isPointInFill(p))return false;
       // A filled band is also a legal line. Its cross-section must be centered
       // on the route, so a background rectangle cannot stand in for geometry.
       const at=offset=>new DOMPoint(a[0]+(b[0]-a[0])*d/length-(b[1]-a[1])*offset/length,a[1]+(b[1]-a[1])*d/length+(b[0]-a[0])*offset/length).matrixTransform(svg.getScreenCTM()).matrixTransform(inverse);
       const extent=sign=>{for(let r=1;r<800;r++)if(!s.isPointInFill(at(sign*r)))return r;return 800;};
       return Math.abs(extent(1)-extent(-1))<=2;
     }))return false;
   }return length>20;
 });
}'''


def comment_count(page, text, count):
    # innerText counts the literal visible comment once, regardless of card tags.
    page.wait_for_function('([text,count])=>document.getElementById("comments").innerText.split(text).length-1===count',arg=[text,count])


def gate_one(c):
    with Application() as app:
        t = tokens(c, app)
        u = api(c, app, '/api/me', token=t['member-a'])['user']
        c.require(u['profile_required'] and u['name'] == '' and u['photo_id'] is None, 'New account requires both profile fields')
        for path, body, method in [('/api/touring-status', {'status': 'touring'}, 'PUT'),
            ('/api/waypoints', {'name': 'Stop', 'lat': 1, 'lon': 2, 'photo_ids': []}, 'POST')]:
            value = api(c, app, path, body, t['member-a'], method, 403)
            c.require(value['error'] == 'profile_required', 'Incomplete profile cannot contribute')
        raw = BytesIO(); image = Image.new('RGBA', (21, 17), (70, 130, 190, 170)); info = PngImagePlugin.PngInfo(); info.add_text('private_source_marker', 'discard-this-synthetic-metadata'); image.save(raw, format='PNG', pnginfo=info)
        asset = api(c, app, '/api/assets', {'png_base64': base64.b64encode(raw.getvalue()).decode()}, t['member-a'], status=201)['asset']
        api(c, app, asset['url'], token=t['member-b'], status=404)
        c.require(api(c, app, '/api/assets', token=t['member-b'])['assets'] == [], 'Own upload listing is private')
        result = request(app, asset['url'], token=t['member-a'], raw=True)
        c.require(result['status'] == 200 and result['content_type'].startswith('image/png'), 'Actual authenticated PNG bytes')
        with Image.open(BytesIO(result['body'])) as clean:
            c.require(clean.size == (21, 17) and clean.convert('RGBA').getpixel((0, 0)) == (70, 130, 190, 170), 'Canonical PNG retains actual pixels and dimensions')
            c.require('private_source_marker' not in clean.info and not clean.getexif(), 'Source image metadata removed')
        for body in [{}, {'name': 'valid', 'photo_id': ''}, {'name': ' ', 'photo_id': asset['id']}]:
            api(c, app, '/api/profile', body, t['member-a'], 'PUT', 400)
        api(c, app, '/api/profile', {'name': '  Sample  member  ', 'photo_id': asset['id']}, t['member-a'], 'PUT')
        c.require(not api(c, app, '/api/me', token=t['member-a'])['user']['profile_required'], 'Profile completes immediately')
        c.require(request(app, asset['url'], token=t['member-b'], raw=True)['status'] == 200, 'Attached profile photo is publicly readable to members')
        api(c, app, '/api/profile', {'name': 'Another', 'photo_id': asset['id']}, t['member-b'], 'PUT', 404)
        before = [fields(row, ('id', 'width', 'height', 'url')) for row in api(c, app, '/api/assets', token=t['member-a'])['assets']]
        for encoded in ['', 'not base64', base64.b64encode(b'not a PNG').decode(), None]:
            api(c, app, '/api/assets', {'png_base64': encoded}, t['member-a'], status=400)
        c.require([fields(row, ('id', 'width', 'height', 'url')) for row in api(c, app, '/api/assets', token=t['member-a'])['assets']] == before, 'Invalid uploads leave no records')
        second = tokens(c, app)['member-a']; api(c, app, '/api/logout', {}, t['member-a'])
        api(c, app, '/api/me', token=t['member-a'], status=401); api(c, app, '/api/me', token=second)
        app.stop(); app.start(); t = tokens(c, app)
        c.require(api(c, app, '/api/me', token=t['member-a'])['user']['name'] == 'Sample  member', 'Profile survives restart with interior whitespace')
        c.require(request(app, asset['url'], token=t['member-b'], raw=True)['body'] == result['body'], 'Stored canonical photo survives restart')
        with browser_session() as browser:
            page = browser.new_page(); page.goto(app.url)
            page.evaluate("async()=>{const {RouteClient}=await import('/app.js');window.probe=new RouteClient();}")
            page.evaluate('(u)=>probe.login(u.username,u.password)', app.seed['users'][0])
            held, handler = hold_first(page, '**/api/me')
            page.evaluate('()=>{window.oldRead=probe.refresh();}'); page.wait_for_function('benchmarkHeld===1')
            page.evaluate('(u)=>probe.login(u.username,u.password)', app.seed['users'][1])
            release(held); page.evaluate('()=>Promise.resolve(oldRead).catch(()=>null)'); page.unroute('**/api/me', handler)
            c.require(page.evaluate('probe.user.id') == app.seed['users'][1]['id'], 'Late prior-account response cannot overwrite current user')
            page.route('**/api/me', lambda route: route.fulfill(status=401, content_type='application/json', body='{"error":"unauthenticated"}'))
            page.evaluate('()=>Promise.resolve(probe.refresh()).catch(()=>null)')
            c.require(page.evaluate('probe.user===null && probe.assets.length===0 && probe.waypointDetail===null && probe.routeDetail===null && Boolean(probe.error)'), 'Current 401 clears private client state')
            page.evaluate('()=>probe.dispose()')


def gate_two(c):
    with Application() as app:
        t, points, ids = setup(c, app)
        r = route(c, app, t['member-b'], '  Mixed CASE route  ', ids[::-1])
        detail = api(c, app, '/api/routes/' + enc(r['id']), token=t['member-a'])
        c.require(detail['route']['title'] == 'Mixed CASE route' and [p['id'] for p in detail['waypoints']] == ids[::-1], 'Ordered shared waypoint references and trimmed title')
        c.require(len(api(c, app, '/api/routes?q=mixed%20case', token=t['member-a'])['routes']) == 1, 'Public ASCII substring filter')
        c.require(api(c, app, '/api/routes?q=not-present', token=t['member-a'])['routes'] == [], 'Nonmatching catalog query')
        before = [fields(row, WP) for row in api(c, app, '/api/waypoints', token=t['member-a'])['waypoints']]
        for lat, lon in [(True, 2), (86, 2), (1, -181), ('1', 2), (None, 2)]:
            api(c, app, '/api/waypoints', {'name': 'Valid name', 'lat': lat, 'lon': lon, 'photo_ids': []}, t['member-a'], status=400)
        for values in [[], [ids[0]], ids + [ids[0]], 'not a list']:
            api(c, app, '/api/routes', {'title': 'Valid title', 'waypoint_ids': values}, t['member-a'], status=400)
        api(c, app, '/api/routes', {'title': 'Valid title', 'waypoint_ids': [ids[0], 'unknown']}, t['member-a'], status=404)
        c.require([fields(row, WP) for row in api(c, app, '/api/waypoints', token=t['member-a'])['waypoints']] == before, 'Invalid foundation operations preserve records')
        app.stop(); app.start(); t = tokens(c, app)
        c.require([p['id'] for p in api(c, app, '/api/routes/' + enc(r['id']), token=t['member-b'])['waypoints']] == ids[::-1], 'Route and waypoint order survive restart')
    c.require(public_run()['passed'], 'Real profile/photo/waypoint/route/SVG browser foundation and literal text')


def gate_three(c):
    with Application() as app:
        t, points, ids = setup(c, app)
        rows = [route(c, app, t['member-a'], title, ids) for title in ['beta', 'Alpha', 'alpha', 'Zulu', 'ALPHA', 'Éclair']]
        def order(token, sort='asc', q=''):
            return [r['id'] for r in api(c, app, '/api/routes?sort=' + sort + '&q=' + enc(q), token=token)['routes']]
        c.require(order(t['member-a']) == [rows[i]['id'] for i in [1, 2, 4, 0, 3, 5]], 'Ascending ASCII-folded Unicode code-point order with stable ties')
        c.require(order(t['member-a'], 'desc') == [rows[i]['id'] for i in [5, 3, 0, 1, 2, 4]], 'Descending preserves equal-title creation order')
        pin(c, app, t['member-a'], rows[0]); pin(c, app, t['member-a'], rows[2])
        c.require(order(t['member-a']) == [rows[i]['id'] for i in [2, 0, 1, 4, 3, 5]], 'Personal pins grouped before independently sorted remainder')
        c.require(order(t['member-a'], 'desc', ' alpha ') == [rows[i]['id'] for i in [2, 1, 4]], 'Filter before pin grouping and stable descending ties')
        c.require(order(t['member-b']) == [rows[i]['id'] for i in [1, 2, 4, 0, 3, 5]], 'Other users do not inherit pins')
        api(c, app, '/api/routes?sort=reverse', token=t['member-a'], status=400)
        with browser_session() as browser:
            page = browser.new_page(); page_login(page, app)
            page.locator('[data-route-id=' + json.dumps(rows[0]['id']) + ']').click(); expect(page.locator('#route-heading')).to_contain_text('beta')
            page.locator('#route-sort').select_option('desc'); page.locator('#route-query').fill('alpha'); page.locator('#apply-catalog').click()
            expect(page.locator('#route-list [data-route-id]')).to_have_count(3)
            c.require(page.locator('#route-list [data-route-id]').evaluate_all('nodes=>nodes.map(n=>n.dataset.routeId)') == [rows[i]['id'] for i in [2, 1, 4]], 'Actual Apply control renders sorted filtered catalog')
            expect(page.locator('#route-heading')).to_contain_text('beta')
            c.require(page.locator('#route-stops [data-stop-id]').evaluate_all('nodes=>nodes.map(n=>n.dataset.stopId)') == ids, 'Filtering does not alter selection or stored waypoint order')


def gate_four(c):
    with Application() as app:
        t, points, ids = setup(c, app); a = route(c, app, t['member-a'], 'First route', ids); b = route(c, app, t['member-b'], 'Second route', ids)
        for _ in range(2): pin(c, app, t['member-a'], a)
        pin(c, app, t['member-a'], b)
        c.require(all(r['pinned'] for r in api(c, app, '/api/routes', token=t['member-a'])['routes']), 'Multiple pins retained, repeated true harmless')
        for _ in range(2): pin(c, app, t['member-a'], a, False)
        c.require(sum(r['pinned'] for r in api(c, app, '/api/routes', token=t['member-a'])['routes']) == 1, 'Repeated unpin is pair-specific and idempotent')
        with browser_session() as browser:
            page = browser.new_page(); page_login(page, app)
            page.locator('[data-route-id=' + json.dumps(a['id']) + ']').click(); expect(page.locator('#route-heading')).to_contain_text('First route')
            button = page.locator('[data-pin-route=' + json.dumps(b['id']) + ']'); box = button.bounding_box()
            c.require(box['width'] >= 40 and box['height'] >= 40, 'Separate pin target has usable declared dimensions')
            with page.expect_response('**/pin') as response: button.click()
            c.require(response.value.status == 200, 'Real pin mutation'); forbid_unrequested_route(page, 'Second route')
            expect(page.locator('#route-heading')).to_contain_text('First route')
            page.locator('#touring-status').select_option('touring')
            c.require(api(c, app, '/api/me', token=t['member-a'])['user']['touring_status'] == 'planned', 'Choosing status does not persist before Submit')
            with page.expect_response('**/api/touring-status') as response: page.locator('#submit-status').click()
            c.require(response.value.status == 200, 'Submit control persists status')
            c.require(api(c, app, '/api/me', token=t['member-a'])['user']['touring_status'] == 'touring', 'Actual selected status saved')
            page.locator('#touring-status').select_option('completed'); page.locator('#logout').click(); expect(page.locator('#workspace')).to_be_hidden()
        before = api(c, app, '/api/me', token=t['member-a'])['user']
        api(c, app, '/api/touring-status', {'status': 'unknown'}, t['member-a'], 'PUT', 400)
        api(c, app, '/api/profile', {'name': before['name'], 'photo_id': before['photo_id']}, t['member-a'], 'PUT')
        point(c, app, t['member-a'], 'Another stop')
        c.require(api(c, app, '/api/me', token=t['member-a'])['user']['touring_status'] == 'touring', 'Profile and waypoint creation preserve submitted status; unsubmitted choice discarded')
        c.require(api(c, app, '/api/me', token=t['member-b'])['user']['touring_status'] == 'planned', 'Touring status belongs to current member only')
        app.stop(); app.start(); t = tokens(c, app)
        c.require(api(c, app, '/api/me', token=t['member-a'])['user']['touring_status'] == 'touring', 'Submitted status survives restart')


def gate_five(c):
    with Application() as app:
        t, points, ids = setup(c, app)
        points.append(point(c,app,t['member-a'],'Third turn',60,-110));ids.append(points[-1]['id'])
        r = route(c, app, t['member-b'], 'Shared route', ids)
        p = points[0]; path = wp_path(p)
        before = fields(p, WP)
        api(c, app, path, {'lat': 20, 'lon': 31, 'revision': 0}, t['member-b'], 'PATCH', 403)
        for lat, lon, rev in [(86, 3, 0), (2, 181, 0), (True, 3, 0), (2, 3, True), (2, 3, -1), (2, 3, 0.0)]:
            api(c, app, path, {'lat': lat, 'lon': lon, 'revision': rev}, t['member-a'], 'PATCH', 400)
        c.require(fields(api(c, app, path, token=t['member-a'])['waypoint'], WP) == before, 'Invalid/foreign edits preserve complete waypoint')
        changed = api(c, app, path, {'lat': 20, 'lon': 31, 'revision': 0, 'name': 'Ignored rename', 'owner_id': 'member-b', 'photo_ids': []}, t['member-a'], 'PATCH')['waypoint']
        c.require(changed['name'] == before['name'] and changed['owner_id'] == before['owner_id'] and changed['photo_ids'] == before['photo_ids'] and changed['revision'] == 1, 'Location changes preserve immutable identity/photos and increment revision once')
        same = api(c, app, path, {'lat': 20, 'lon': 31, 'revision': 1}, t['member-a'], 'PATCH')['waypoint']
        c.require(fields(same, WP) == fields(changed, WP), 'Matching identical coordinate edit is a no-op')
        api(c, app, path, {'lat': 20, 'lon': 31, 'revision': 0}, t['member-a'], 'PATCH', 409)
        resolved = api(c, app, '/api/routes/' + enc(r['id']), token=t['member-b'])['waypoints'][0]
        c.require(resolved['lat'] == 20 and resolved['lon'] == 31, 'Other user route resolves current shared coordinates')
        with browser_session() as browser:
            page = browser.new_page(); page_login(page, app)
            page.locator('#route-list [data-route-id]').click(); expect(page.locator('#route-detail')).to_be_visible()
            page.locator('#waypoint-list [data-waypoint-id=' + json.dumps(p['id']) + ']').click(); expect(page.locator('#waypoint-detail')).to_be_visible()
            map_matches(page, [changed, *points[1:]])
            old_map = page.locator('#map').screenshot()
            api(c, app, path, {'lat': -40, 'lon': -75, 'revision': 1}, t['member-a'], 'PATCH')
            page.locator('#edit-lat').fill('24'); page.locator('#edit-lon').fill('35'); page.locator('#save-location').click()
            expect(page.locator('#error')).not_to_have_text('')
            page.wait_for_function('Number(document.getElementById("edit-lat").value) === -40')
            map_matches(page, [{**changed, 'lat': -40, 'lon': -75}, *points[1:]])
            c.require(page.locator('#map').screenshot() != old_map, 'Conflict refresh updates actual displayed map geometry')
            page.locator('#edit-lat').fill('24'); page.locator('#edit-lon').fill('35'); page.locator('#save-location').click()
            expect(page.locator('#error')).to_have_text('')
            c.require(api(c, app, path, token=t['member-a'])['waypoint']['revision'] == 3, 'Intentional retry uses the refreshed revision')
            map_matches(page,[{**changed,'lat':24,'lon':35},*points[1:]])


def gate_six(c):
    with Application() as app:
        t, points, ids = setup(c, app); path = wp_path(points[0]) + '/comments'
        body = {'text': '  Keep  inner\nWhitespace <b>literal</b>  ', 'request_id': 'synthetic-key', 'author_id': 'member-b'}
        def send(_): return request(app, path, body, t['member-a'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool: results = list(pool.map(send, range(3)))
        c.require(sorted(r['status'] for r in results) == [200, 200, 201], 'Concurrent identical comments commit exactly once')
        first = results[0]['body']['comment']
        c.require(all(r['body']['comment']['id'] == first['id'] for r in results), 'Semantic replay returns stable stored comment ID')
        c.require(first['text'] == body['text'].strip() and first['author']['id'] == 'member-a', 'Normalized literal comment uses actual author')
        api(c, app, path, {**body, 'text': 'Different'}, t['member-a'], status=409)
        api(c, app, wp_path(points[1]) + '/comments', body, t['member-a'], status=409)
        api(c, app, path, body, t['member-b'], status=201)
        api(c, app, path, {'text': ' ', 'request_id': 'later-valid'}, t['member-a'], status=400)
        api(c, app, path, {'text': 'Later valid', 'request_id': 'later-valid'}, t['member-a'], status=201)
        comments = api(c, app, wp_path(points[0]), token=t['member-b'])['comments']
        c.require(len(comments) == 3 and comments[0]['id'] == first['id'] and comments[-1]['text'] == 'Later valid', 'Immediate public ordered comments with no duplicate or invalid-key consumption')
        app.stop(); app.start(); t = tokens(c, app)
        c.require(api(c, app, path, body, t['member-a'])['comment']['id'] == first['id'], 'Successful comment replay survives restart')
        with browser_session() as browser:
            page = browser.new_page(); page_login(page, app)
            page.locator('#waypoint-list [data-waypoint-id=' + json.dumps(points[1]['id']) + ']').click(); expect(page.locator('#waypoint-detail')).to_be_visible()
            lost = []
            def lose(route):
                if lost: route.continue_(); return
                lost.append(route.fetch()); route.abort()
            page.route('**/api/waypoints/*/comments', lose)
            page.locator('#comment-text').fill('A new <b>literal</b> browser comment'); page.locator('#send-comment').click()
            expect(page.locator('#error')).not_to_have_text('')
            c.require(len(api(c, app, wp_path(points[1]), token=t['member-a'])['comments']) == 1, 'First send committed despite lost response')
            page.locator('#send-comment').click(); comment_count(page,'A new <b>literal</b> browser comment',1)
            expect(page.locator('#comment-text')).to_have_value('')
            c.require(len(api(c, app, wp_path(points[1]), token=t['member-a'])['comments']) == 1, 'Visible retry reuses the original key')
            c.require(page.locator('#comments b').count() == 0, 'Browser renders comments literally')
            page.locator('#comment-text').fill('A new <b>literal</b> browser comment'); page.locator('#send-comment').click()
            comment_count(page,'A new <b>literal</b> browser comment',2)
            c.require(len(api(c, app, wp_path(points[1]), token=t['member-a'])['comments']) == 2, 'New intentional duplicate text gets a new key')
            page.unroute('**/api/waypoints/*/comments', lose)
            page.evaluate("async()=>{const {RouteClient}=await import('/app.js');window.probe=new RouteClient();}")
            page.evaluate('(u)=>probe.login(u.username,u.password)', app.seed['users'][0])
            page.evaluate('(id)=>probe.openWaypoint(id)', points[0]['id'])
            held, handler = hold_first(page, '**/api/waypoints/*/comments')
            page.evaluate('()=>{window.oldSend=probe.comment("Delayed synthetic comment","delayed-key");}')
            page.wait_for_function('benchmarkHeld===1')
            page.evaluate('(id)=>probe.openWaypoint(id)', points[1]['id'])
            release(held); page.evaluate('()=>Promise.resolve(oldSend).catch(()=>null)'); page.unroute('**/api/waypoints/*/comments', handler)
            c.require(page.evaluate('probe.waypointDetail.waypoint.id') == points[1]['id'], 'Late comment response cannot restore obsolete waypoint selection')
            page.evaluate('()=>probe.dispose()')


GATES = [gate_one, gate_two, gate_three, gate_four, gate_five, gate_six]


def main():
    results, errors = [], []
    for index, gate in enumerate(GATES, 1):
        checks = Checks(); row = {'ru_id': f'RU-{index:03d}', 'passed': False}
        try: gate(checks); row.update(passed=True, detail='All executable checks passed')
        except (AssertionError, KeyError, TypeError, IndexError, ValueError, StopIteration, BrowserTimeout) as error: row['detail'] = type(error).__name__ + ': ' + str(error)
        except Exception as error:
            row['detail'] = 'Unattributed evaluator/environment error: ' + repr(error)
            errors.append({'ru_id': row['ru_id'], 'traceback': traceback.format_exc()})
        row['checks_passed'] = checks.passed; results.append(row)
    print(json.dumps({'harness_ok': not errors, 'results': results, 'infrastructure_errors': errors})); return 0 if not errors else 2


if __name__ == '__main__': raise SystemExit(main())
