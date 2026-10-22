"""Six behavior gates. Candidate modules are never imported into this evaluator."""
import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO
import json
import math
import re
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, '/public_tests')
from conversation_support import Application, ProviderService, browser_session, request, run_as
from fixtures import screenshot, photo
from test_public import conversation_fields, workspace_fields
from PIL import Image
from playwright.sync_api import expect, TimeoutError as BrowserTimeout

FIRST = SECOND = BAD = None
FIRST_MESSAGES = [{'sender': 'me', 'text': 'The meeting begins at noon'}, {'sender': 'peer', 'text': 'The notes are ready'}]
SECOND_MESSAGES = [{'sender': 'me', 'text': 'The draft is ready'}, {'sender': 'peer', 'text': 'Please share the draft'}]


class Checks:
    def __init__(self): self.passed = 0
    def require(self, truth, detail):
        assert truth, detail
        self.passed += 1


def api(app, path, body=None, token=None, status=200, method=None):
    reply = request(app, path, body, token, method)
    assert reply['status'] == status, (path, 'expected status', status, 'actual', reply['status'], reply['body'])
    return reply['body']


def login(app, index=0):
    user = app.accounts['users'][index]
    result = api(app, '/api/login', {'username': user['username'], 'password': user['password']})
    assert isinstance(result['token'], str) and result['token']
    assert result['user']['id'] == user['id'] and result['user']['username'] == user['username']
    return result['token']


def new_conversation(app, token, title='Review notes'):
    return api(app, '/api/conversations', {'title': title}, token, 201)['conversation']


def upload(app, token, raw, kind='screenshot', label='Synthetic input'):
    return api(app, '/api/assets', {'label': label, 'kind': kind, 'image_base64': base64.b64encode(raw).decode()}, token, 201)['asset']


def conversation(app, token, key):
    return conversation_fields(api(app, '/api/conversations/' + key, token=token)['conversation'])


def extract(app, token, conversation_id, asset_id, key='seed'):
    return api(app, '/api/extract', {'conversation_id': conversation_id, 'asset_id': asset_id, 'request_id': key}, token)


def advice_fields(value):
    return {key: value[key] for key in ('id', 'question', 'text', 'context_revision')}


def ranking_fields(value):
    return {'id': value['id'], 'items': [{key: row[key] for key in ('asset_id', 'score', 'reasons')} for row in value['items']]}


def scores_match(actual, expected):
    return len(actual) == len(expected) and all(
        row['asset_id'] == wanted['asset_id'] and row['reasons'] == wanted['reasons']
        and type(row['score']) in (int, float) and math.isclose(row['score'], wanted['score'], rel_tol=1e-9, abs_tol=1e-9)
        for row, wanted in zip(actual, expected))


def image_files(app):
    code = """import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]);print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}))
"""
    return json.loads(run_as(1000, code, app.project / 'data/images'))


def wait_routes(page, routes, expected):
    deadline = time.monotonic() + 5
    while len(routes) < expected and time.monotonic() < deadline:
        page.wait_for_timeout(25)
    assert len(routes) == expected, 'Expected real pending request was not observed'


def displayed_color(page, asset_id, color, checks):
    # Observe actual pixels, without requiring an img, canvas or CSS implementation.
    row = page.locator('[data-asset-id="' + asset_id + '"]')
    expect(row).to_be_visible()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with Image.open(BytesIO(row.screenshot())) as image:
            count = sum(1 for pixel in image.convert('RGB').getdata()
                        if all(abs(channel - target) <= 12 for channel, target in zip(pixel, color)))
        if count >= 4:
            checks.require(True, 'The uploaded synthetic image contributes visible pixels')
            return
        page.wait_for_timeout(50)
    checks.require(False, 'Image was fetched but its distinctive content was not visibly displayed')


@contextmanager
def world(seed=False):
    with ProviderService() as provider, Application(provider_url=provider.url) as app:
        a, b = login(app), login(app, 1)
        one, two = new_conversation(app, a), new_conversation(app, a, 'Separate review')
        foreign = new_conversation(app, b, 'Other workspace')
        screen = upload(app, a, FIRST)
        if seed: extract(app, a, one['id'], screen['id'])
        yield app, provider, a, b, one['id'], two['id'], foreign['id'], screen['id']


def browser_login(page, app, index=0):
    user = app.accounts['users'][index]
    page.goto(app.url)
    page.locator('#username').fill(user['username'])
    page.locator('#password').fill(user['password'])
    page.locator('#login').click()
    expect(page.locator('#workspace')).to_be_visible()


def gate_one(c):
    with world() as (app, provider, a, b, one, two, foreign, screen):
        api(app, '/api/workspace', status=401)
        api(app, '/api/login', {'username': app.accounts['users'][0]['username'], 'password': 'wrong'}, status=401)
        api(app, '/api/login', b'[]', status=400)
        api(app, '/api/login', b'{', status=400)
        api(app, '/api/conversations/' + one, token=b, status=404)
        api(app, '/api/assets/' + screen + '/image', token=b, status=404)
        before = workspace_fields(api(app, '/api/workspace', token=a))
        c.require([row['id'] for row in before['conversations']] == [one, two], 'Owned conversations in creation order')
        c.require(before['profile'] == {'tone': 'neutral', 'goal': 'clarity', 'revision': 0}, 'Fresh synthetic profile')
        body = request(app, '/api/assets/' + screen + '/image', token=a, raw=True)
        c.require(body['status'] == 200 and body['content_type'].split(';')[0] == 'image/png', 'Owned actual PNG response')
        with Image.open(BytesIO(body['body'])) as image:
            c.require(image.mode == 'RGB' and image.size == (1100, 220) and 'SyntheticMarker' not in image.info, 'Canonical RGB PNG without source metadata')
            image.load()
        before_images = image_files(app)
        for fields in [{'image_base64': 'bad'}, {'image_base64': base64.b64encode(b'not png').decode()}, {'label': ' '}, {'kind': 'unknown'}]:
            api(app, '/api/assets', {'label': 'Valid', 'kind': 'screenshot', 'image_base64': base64.b64encode(FIRST).decode(), **fields}, a, 400)
        c.require(workspace_fields(api(app, '/api/workspace', token=a)) == before, 'Invalid uploads preserve registered state')
        c.require(image_files(app) == before_images, 'Invalid uploads leave no lasting files or modifications')
        second_session = login(app)
        c.require(second_session != a and len(a) >= 32, 'Independent nontrivial session tokens')
        api(app, '/api/logout', {}, a)
        api(app, '/api/workspace', token=a, status=401)
        c.require(workspace_fields(api(app, '/api/workspace', token=second_session)) == before, 'Logout invalidates only its session')
        app.stop(); app.start(); a = login(app)
        c.require(workspace_fields(api(app, '/api/workspace', token=a)) == before, 'Workspace survives process restart')
        c.require(provider.requests() == [], 'Baseline operations do not call provider')
        blue = upload(app, a, photo('#1199dd'), 'photo', 'Blue synthetic shape')
        pink = upload(app, a, photo('#dd4499'), 'photo', 'Pink synthetic shape')
        with browser_session() as browser:
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            page = context.new_page(); browser_login(page, app)
            expect(page.locator('[data-conversation-id]')).to_have_count(2)
            displayed_color(page, blue['id'], (17, 153, 221), c)
            displayed_color(page, pink['id'], (221, 68, 153), c)
            page.locator('[data-conversation-id="' + one + '"]').click()
            for width, height in [(390, 844), (1280, 900)]:
                page.set_viewport_size({'width': width, 'height': height})
                c.require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Responsive page fits viewport')
            fresh = context.new_page(); fresh.goto(app.url)
            expect(fresh.locator('#workspace')).to_be_hidden(); fresh.close()
            page.locator('#logout').click(); expect(page.locator('#workspace')).to_be_hidden()
            expect(page.locator('#asset-list')).to_have_text(''); expect(page.locator('#transcript')).to_have_text('')
            context.close()


def gate_two(c):
    with world() as (app, provider, a, b, one, two, foreign, screen):
        first = extract(app, a, one, screen)['conversation']
        c.require(conversation_fields(first)['messages'] == FIRST_MESSAGES and first['revision'] == 1 and not first['advice'], 'Actual screenshot OCR appends labeled lines once')
        second_screen = upload(app, a, SECOND)
        second = api(app, '/api/extract', {'conversation_id': one, 'asset_id': second_screen['id'], 'request_id': 'second', 'messages': [{'sender': 'me', 'text': 'injected'}]}, a)['conversation']
        c.require(conversation_fields(second)['messages'] == FIRST_MESSAGES + SECOND_MESSAGES and second['revision'] == 2, 'New image contents replace no prior transcript; ignore caller text')
        c.require(conversation(app, a, two)['messages'] == [], 'Only selected conversation changes')
        wrong = upload(app, a, photo(), 'photo')
        bad = upload(app, a, BAD)
        other = upload(app, b, FIRST)
        for conversation_id, asset_id, status in [(foreign, screen, 404), (one, other['id'], 404), (one, wrong['id'], 400), (one, bad['id'], 422)]:
            api(app, '/api/extract', {'conversation_id': conversation_id, 'asset_id': asset_id, 'request_id': 'failure'}, a, status)
        c.require(conversation(app, a, one) == conversation_fields(second) and provider.requests() == [], 'Rejected extraction is atomic and never calls provider')
        with browser_session() as browser:
            page = browser.new_page(); browser_login(page, app)
            page.locator('[data-conversation-id="' + two + '"]').click()
            page.locator('[data-screenshot-id="' + second_screen['id'] + '"]').check()
            page.locator('#extract').click()
            expect(page.locator('#transcript')).to_contain_text('The draft is ready')
            expect(page.locator('#transcript')).to_contain_text('Please share the draft')
            expect(page.locator('#advice-list')).to_have_text('')
            c.require(conversation(app, a, two)['messages'] == SECOND_MESSAGES, 'Real extraction button targets selected conversation')
            page.close()


def gate_three(c):
    with world(seed=True) as (app, provider, a, b, one, two, foreign, screen):
        question = 'What should happen next?'
        body = {'conversation_id': one, 'question': '  ' + question + '  ', 'request_id': 'coach', 'messages': [], 'advice': 'caller', 'system_prompt': 'caller', 'profile': {'tone': 'caller'}}
        provider.configure(responses={'/coach': {'advice': '  <b>Keep this literal</b>  '}})
        result = api(app, '/api/coach', body, a)['advice']
        expected = {'system_prompt': 'Offer clear and respectful communication suggestions.', 'profile': {'tone': 'neutral', 'goal': 'clarity'}, 'messages': FIRST_MESSAGES, 'question': question}
        c.require(provider.requests()[-1]['payload'] == expected, 'Exact stored text-only context; no IDs, credentials, images or caller override')
        c.require(advice_fields(result) == {'id': result['id'], 'question': question, 'text': '<b>Keep this literal</b>', 'context_revision': 1} and isinstance(result['id'], str) and bool(result['id']), 'Use trimmed provider advice and original context revision')
        previous = conversation(app, a, one)
        c.require(previous['messages'] == FIRST_MESSAGES and previous['revision'] == 1 and previous['advice'] == [advice_fields(result)], 'Advice remains separate and durable')
        count = len(provider.requests())
        api(app, '/api/coach', {**body, 'conversation_id': foreign, 'request_id': 'foreign'}, a, 404)
        api(app, '/api/coach', {**body, 'conversation_id': two, 'request_id': 'empty'}, a, 409)
        c.require(len(provider.requests()) == count, 'Validate owner and nonempty transcript before provider')
        for reply in [{}, {'advice': False}, {'advice': ''}, {'advice': '  '}, {'advice': 'x' * 4001}]:
            provider.configure(responses={'/coach': reply})
            api(app, '/api/coach', {**body, 'request_id': 'recovery'}, a, 502)
            c.require(conversation(app, a, one) == previous, 'Invalid provider advice preserves prior state')
        for fault in ['http_error', 'invalid_json']:
            provider.configure(faults={'/coach': fault})
            api(app, '/api/coach', {**body, 'request_id': 'recovery'}, a, 502)
            c.require(conversation(app, a, one) == previous, 'Transport or format failure preserves prior state')
        provider.configure(responses={'/coach': {'advice': 'x' * 4000}})
        c.require(len(api(app, '/api/coach', {**body, 'request_id': 'recovery'}, a)['advice']['text']) == 4000, 'Inclusive advice size boundary and failed-key recovery')
        extra = upload(app, a, SECOND); extract(app, a, one, extra['id'], 'more-text')
        # Context preference updates require the RU-004 update interface; this dependency is recorded.
        api(app, '/api/profile', {'tone': 'Direct and Kind', 'goal': 'Confirm the plan', 'revision': 0}, a, method='PUT')
        provider.configure(responses={'/coach': {'advice': '<b>Browser advice</b>'}})
        with browser_session() as browser:
            page = browser.new_page(); browser_login(page, app)
            page.locator('[data-conversation-id="' + one + '"]').click()
            page.locator('#question').fill('Browser question'); page.locator('#coach').click()
            expect(page.locator('#advice-list')).to_contain_text('<b>Browser advice</b>')
            expect(page.locator('#advice-list b')).to_have_count(0)
            last = provider.requests()[-1]['payload']
            c.require(last['messages'] == FIRST_MESSAGES + SECOND_MESSAGES and last['question'] == 'Browser question' and last['profile'] == {'tone': 'Direct and Kind', 'goal': 'Confirm the plan'}, 'Browser uses latest complete transcript, stored profile and question')
            page.close()


def gate_four(c):
    with world() as (app, provider, a, b, one, two, foreign, screen):
        before = conversation(app, a, one)
        profile = api(app, '/api/profile', {'tone': '  Calm  and Direct  ', 'goal': '  Clear Next Step  ', 'revision': 0, 'owner': app.accounts['users'][1]['id']}, a, method='PUT')['profile']
        c.require({key: profile[key] for key in ('tone', 'goal', 'revision')} == {'tone': 'Calm  and Direct', 'goal': 'Clear Next Step', 'revision': 1}, 'Outer trim, preserve case/internal whitespace, increment once')
        for update, status in [({'revision': 0}, 409), ({'revision': True}, 400), ({'revision': -1}, 400), ({'tone': ''}, 400), ({'goal': ' '}, 400), ({'tone': 'x' * 121}, 400)]:
            api(app, '/api/profile', {'tone': 'valid', 'goal': 'valid', 'revision': 1, **update}, a, status, 'PUT')
            actual = api(app, '/api/workspace', token=a)['profile']
            c.require(all(actual[key] == profile[key] for key in ('tone', 'goal', 'revision')), 'Invalid/conflicting preferences preserve both fields and revision')
        c.require(api(app, '/api/workspace', token=b)['profile']['revision'] == 0 and conversation(app, a, one) == before and provider.requests() == [], 'Preference edits affect only the current profile')
        with browser_session() as browser:
            page = browser.new_page(); browser_login(page, app)
            expect(page.locator('#tone')).to_have_value('Calm  and Direct')
            api(app, '/api/profile', {'tone': 'Authoritative', 'goal': 'New goal', 'revision': 1}, a, method='PUT')
            page.locator('#tone').fill('Stale edit'); page.locator('#save-profile').click()
            expect(page.locator('#error')).not_to_have_text('')
            expect(page.locator('#tone')).to_have_value('Authoritative')
            page.locator('#tone').fill('Deliberate edit')
            with page.expect_response('**/api/profile') as saved: page.locator('#save-profile').click()
            c.require(saved.value.status == 200, 'Explicit save after conflict uses refreshed revision')
            c.require(api(app, '/api/workspace', token=a)['profile']['tone'] == 'Deliberate edit', 'Real preference form persists chosen update')
            page.close()


def gate_five(c):
    with world() as (app, provider, a, b, one, two, foreign, screen):
        first = upload(app, a, photo('#1199dd'), 'photo', 'Blue shape')
        second = upload(app, a, photo('#dd4499'), 'photo', 'Pink shape')
        other = upload(app, b, photo(), 'photo')
        ids = [first['id'], second['id']]
        rows = [{'asset_id': ids[1], 'score': 72.25, 'reasons': ['  Preserve spaces  ', '<b>Literal reason</b>']}, {'asset_id': ids[0], 'score': 72.25, 'reasons': []}]
        provider.configure(responses={'/photo-scores': {'scores': rows}})
        body = {'asset_ids': ids, 'request_id': 'ranking', 'scores': [{'score': 999}], 'owner': 'ignored'}
        result = api(app, '/api/rank', body, a)['ranking']
        c.require(scores_match(ranking_fields(result)['items'], sorted(rows, key=lambda row: row['asset_id'])), 'Actual provider scores, reasons and ascending ID tie break')
        payload = provider.requests()[-1]['payload']
        c.require(set(payload) == {'preferences', 'images'} and payload['preferences'] == {'tone': 'neutral', 'goal': 'clarity'} and [row['asset_id'] for row in payload['images']] == ids, 'Only current preferences and selected images in request order')
        for row in payload['images']:
            served = request(app, '/api/assets/' + row['asset_id'] + '/image', token=a, raw=True)
            c.require(set(row) == {'asset_id', 'mime_type', 'image_base64'} and row['mime_type'] == 'image/png' and base64.b64decode(row['image_base64']) == served['body'], 'Provider receives exact actual canonical PNG bytes')
        previous = [ranking_fields(value) for value in api(app, '/api/rankings', token=a)['rankings']]
        count = len(provider.requests())
        for selected, status in [([], 400), ([ids[0], ids[0]], 400), ([True], 400), ([other['id']], 404), ([screen], 400)]:
            api(app, '/api/rank', {'asset_ids': selected, 'request_id': 'invalid'}, a, status)
        c.require(len(provider.requests()) == count, 'Validate all references before any provider call')
        invalid = [[], [rows[0], rows[0]], [{**rows[0], 'asset_id': 'unknown'}, rows[1]], [{**rows[0], 'reasons': [7]}, rows[1]]]
        invalid += [[{**rows[0], 'score': value}, rows[1]] for value in [True, -1, 101, '72.25', float('nan'), float('inf')]]
        for bad_rows in invalid:
            provider.configure(responses={'/photo-scores': {'scores': bad_rows}})
            api(app, '/api/rank', {**body, 'request_id': 'recovery'}, a, 502)
            c.require([ranking_fields(value) for value in api(app, '/api/rankings', token=a)['rankings']] == previous, 'Invalid scores do not create a ranking')
        provider.configure(responses={'/photo-scores': {'scores': [{**rows[0], 'score': 0}, {**rows[1], 'score': 100}]}})
        c.require([row['score'] for row in api(app, '/api/rank', {**body, 'request_id': 'recovery'}, a)['ranking']['items']] == [100, 0], 'Score bounds inclusive and descending score ordering')
        c.require(api(app, '/api/rankings', token=b)['rankings'] == [], 'Rankings are owned')
        # Inject a filesystem fault without assuming the candidate SQL schema.
        raw = request(app, '/api/assets/' + ids[0] + '/image', token=a, raw=True)['body']
        scan = """import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]);matches=[]
for path in root.rglob('*'):
 if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==sys.argv[2]:matches.append(str(path))
print(json.dumps(matches))
"""
        matches = json.loads(run_as(1000, scan, app.project / 'data/images', hashlib.sha256(raw).hexdigest()))
        c.require(bool(matches), 'An actual canonical PNG is stored under the documented upload directory')
        file = matches[0]; count = len(provider.requests())
        run_as(1000, "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.rename(p.with_name(p.name+'.held'))", file)
        # The frozen contract requires rejection, but does not specify a unique status for damaged stored images.
        c.require(request(app, '/api/rank', {**body, 'request_id': 'damaged'}, a)['status'] >= 400, 'Missing selected file rejects ranking')
        run_as(1000, "import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(b'not a PNG')", file)
        c.require(request(app, '/api/rank', {**body, 'request_id': 'damaged'}, a)['status'] >= 400, 'Corrupt selected file rejects ranking')
        c.require(len(provider.requests()) == count, 'Read and validate every image before provider')
        run_as(1000, "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.unlink();p.with_name(p.name+'.held').rename(p)", file)
        browser_rows = [{**row, 'reasons': [*row['reasons'], 'New browser ranking']} for row in rows]
        provider.configure(responses={'/photo-scores': {'scores': browser_rows}})
        with browser_session() as browser:
            page = browser.new_page(); browser_login(page, app)
            for key in ids: page.locator('[data-photo-id="' + key + '"]').check()
            page.locator('#rank').click()
            latest = page.locator('[data-ranked-asset-id]').filter(has_text='New browser ranking')
            expect(latest).to_have_count(2)
            expect(page.locator('#ranking')).to_contain_text('<b>Literal reason</b>')
            expect(page.locator('#ranking b')).to_have_count(0)
            c.require(latest.evaluate_all('(nodes)=>nodes.map(node=>node.dataset.rankedAssetId)') == sorted(ids), 'Actual rank controls render provider ordering')
            for key in ids:
                text = page.locator('[data-ranked-asset-id="' + key + '"]').filter(has_text='New browser ranking').inner_text().replace(key, '')
                numbers = re.findall(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?', text)
                c.require(any(math.isclose(float(number), 72.25, rel_tol=1e-9, abs_tol=1e-9) for number in numbers), 'Visible score accepts equivalent numeric spelling')
            page.close()


def gate_six(c):
    with world(seed=True) as (app, provider, a, b, one, two, foreign, screen):
        question = 'Replay this question'
        body = {'conversation_id': one, 'question': question, 'request_id': 'shared-key'}
        provider.configure(responses={'/coach': {'advice': 'Durable suggestion'}})
        count = len(provider.requests())
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: api(app, '/api/coach', body, a), range(4)))
        expected = advice_fields(values[0]['advice'])
        c.require(all(advice_fields(value['advice']) == expected for value in values) and len(provider.requests()) == count + 1, 'Concurrent duplicates commit once and return one saved result')
        c.require(len(conversation(app, a, one)['advice']) == 1, 'Only one advice persisted')
        api(app, '/api/coach', {**body, 'question': 'Changed'}, a, 409)
        api(app, '/api/extract', {'conversation_id': one, 'asset_id': screen, 'request_id': 'shared-key'}, a, 409)
        c.require(advice_fields(api(app, '/api/coach', {**body, 'question': '  ' + question + '  ', 'ignored': True}, a)['advice']) == expected and len(provider.requests()) == count + 1, 'Trimmed semantic equality and ignored extras reuse saved result')
        provider.configure(faults={'/coach': 'http_error'})
        api(app, '/api/coach', {**body, 'request_id': 'failed-then-successful'}, a, 502)
        provider.configure(responses={'/coach': {'advice': 'Recovered request'}})
        c.require(api(app, '/api/coach', {**body, 'request_id': 'failed-then-successful'}, a)['advice']['text'] == 'Recovered request', 'Failed requests do not reserve their key')
        snapshot = extract(app, a, one, screen, 'extract-key')['conversation']
        extract(app, a, one, screen, 'new-extract')
        c.require(conversation_fields(extract(app, a, one, screen, 'extract-key')['conversation']) == conversation_fields(snapshot), 'Extraction replay returns saved snapshot rather than current transcript')
        other_screen = upload(app, b, FIRST)
        extract(app, b, foreign, other_screen['id'], 'shared-key')
        c.require(conversation(app, b, foreign)['revision'] == 1, 'Different users have independent request namespaces')
        image = upload(app, a, photo(), 'photo')
        rank_body = {'asset_ids': [image['id']], 'request_id': 'rank-key'}
        provider.configure()
        ranking = ranking_fields(api(app, '/api/rank', rank_body, a)['ranking'])
        count = len(provider.requests())
        current = conversation(app, a, one)
        app.stop(); app.start(); a = login(app)
        c.require(conversation(app, a, one) == current, 'Transcript/advice survive restart')
        c.require(advice_fields(api(app, '/api/coach', body, a)['advice']) == expected, 'Advice replay survives new session/process')
        c.require(conversation_fields(extract(app, a, one, screen, 'extract-key')['conversation']) == conversation_fields(snapshot), 'Extraction replay survives restart')
        c.require(ranking_fields(api(app, '/api/rank', rank_body, a)['ranking']) == ranking and len(provider.requests()) == count, 'Ranking replay survives restart without provider')
        with browser_session() as browser:
            page = browser.new_page(); page.goto(app.url + '/health')
            user = app.accounts['users'][0]
            page.evaluate("async user=>{const {WorkspaceClient}=await import('/app.js');window.client=new WorkspaceClient();await client.login(user.username,user.password);}", user)
            page.evaluate('(id)=>client.openConversation(id)', one)
            calls = []
            def lose_reply(route):
                calls.append(route.request.post_data_json)
                if len(calls) == 1:
                    response = route.fetch(); assert response.status == 200; route.abort('failed')
                else: route.continue_()
            provider.configure(responses={'/coach': {'advice': 'Saved despite transport loss'}})
            page.route('**/api/coach', lose_reply)
            count = len(provider.requests())
            page.evaluate("()=>client.coach('Retry browser intent')")
            page.evaluate('()=>client.refresh()')
            page.evaluate("()=>client.coach('  Retry browser intent  ')")
            c.require(len(calls) == 2 and calls[0]['request_id'] == calls[1]['request_id'] and calls[0]['conversation_id'] == calls[1]['conversation_id'] and calls[0]['question'].strip() == calls[1]['question'].strip(), 'Lost-reply retry preserves semantic payload and original key across refresh')
            c.require(len(provider.requests()) == count + 1, 'Browser retry causes only one provider request')
            page.unroute('**/api/coach', lose_reply)
            calls.clear(); page.route('**/api/coach', lose_reply)
            page.evaluate("()=>client.coach('Abandoned question')")
            page.evaluate("()=>client.coach('Different question')")
            c.require(len(calls) == 2 and calls[0]['request_id'] != calls[1]['request_id'], 'New question abandons old retry key')
            page.unroute('**/api/coach', lose_reply)
            held = []
            page.route('**/api/coach', lambda route: held.append((route, route.fetch())))
            page.evaluate("()=>{window.old=client.coach('Delayed question');}")
            wait_routes(page, held, 1)
            page.evaluate("()=>{window.duplicate=client.coach('Delayed question');}")
            # A correct deduplicator may return the original pending promise.
            # Observe network effects without requiring that duplicate promise to resolve early.
            page.wait_for_timeout(150)
            c.require(len(held) == 1, 'Pending same intent does not launch duplicates')
            page.evaluate('(id)=>client.openConversation(id)', two)
            held[0][0].fulfill(response=held[0][1]); page.evaluate('()=>old')
            c.require(page.evaluate('client.conversation.id') == two and page.evaluate('client.conversation.advice.length') == 0, 'Previous-conversation response cannot replace current selection')
            held.clear(); page.evaluate('(id)=>client.openConversation(id)', one)
            page.evaluate("()=>{window.old=client.coach('Old user request');}"); wait_routes(page, held, 1)
            other = app.accounts['users'][1]
            page.evaluate('(user)=>client.login(user.username,user.password)', other)
            held[0][0].fulfill(response=held[0][1]); page.evaluate('()=>old')
            c.require(page.evaluate('client.conversation') is None and one not in page.evaluate('client.workspace.conversations.map(row=>row.id)'), 'New login cannot receive an old user result')
            page.evaluate('()=>client.dispose()'); page.close()


GATES = [gate_one, gate_two, gate_three, gate_four, gate_five, gate_six]


def main():
    global FIRST, SECOND, BAD
    # Reject unusable OCR fixtures before candidate execution and before scoring.
    try:
        FIRST = screenshot(['Me: The meeting begins at noon', 'Peer: The notes are ready'])
        SECOND = screenshot(['Me: The draft is ready', 'Peer: Please share the draft'])
        BAD = screenshot(['Me: The draft is ready', 'Unknown: The notes are ready'])
    except Exception:
        print(json.dumps({'harness_ok': False, 'results': [], 'infrastructure_errors': [traceback.format_exc()]}))
        return 2
    results, errors = [], []
    for index, gate in enumerate(GATES, 1):
        checks = Checks(); row = {'ru_id': f'RU-{index:03d}', 'passed': False}
        try:
            gate(checks); row.update(passed=True, detail='All executable checks passed')
        except (AssertionError, KeyError, TypeError, IndexError, ValueError, StopIteration, BrowserTimeout) as error:
            row['detail'] = type(error).__name__ + ': ' + str(error)
        except Exception as error:
            row['detail'] = 'Unattributed evaluator/environment error: ' + repr(error)
            errors.append({'ru_id': row['ru_id'], 'traceback': traceback.format_exc()})
        row['checks_passed'] = checks.passed; results.append(row)
    print(json.dumps({'harness_ok': not errors, 'results': results, 'infrastructure_errors': errors}))
    return 0 if not errors else 2


if __name__ == '__main__': raise SystemExit(main())
