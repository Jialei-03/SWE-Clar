"""Private marketplace behavior gates. Candidate implementation is accessed through HTTP and the declared browser interface."""
import concurrent.futures
from copy import deepcopy
import json
import re
from pathlib import Path
import sys
import traceback
from urllib.parse import quote
sys.path.insert(0, '/public_tests')
from marketplace_support import Application, CandidateFailure, browser_session, request
from test_public import login, page_login, run as public_regressions
from playwright.sync_api import expect, TimeoutError as BrowserTimeout, Error as BrowserError


class Checks:
    def __init__(self): self.passed = []
    def require(self, value, name):
        if not value: raise CandidateFailure(name)
        self.passed.append(name)


LISTING_FIELDS = ('id', 'seller_id', 'title', 'price_cents', 'reference_price_cents', 'previous_price_cents', 'created_at', 'revision', 'status', 'labels')
OFFER_FIELDS = ('id', 'listing_id', 'buyer_id', 'amount_cents', 'counter_amount_cents', 'status', 'version')
AGREEMENT_FIELDS = ('id', 'listing_id', 'offer_id', 'buyer_id', 'seller_id', 'amount_cents')
MONEY_VISIBLE = r'''({selector, amount}) => [...document.querySelectorAll(selector)].some(node =>
 (node.textContent.match(/[+-]?\d[\d,]*(?:\.\d+)?(?:e[+-]?\d+)?/gi) || [])
 .some(value => Number(value.replaceAll(',', '')) === amount))'''


def project(value, fields): return {key: value[key] for key in fields}
def snapshot(value):
    return {'listing': project(value['listing'], LISTING_FIELDS),
            'questions': [{key: q[key] for key in ('id', 'listing_id', 'text')} | {'author': project(q['author'], ('id', 'username'))} for q in value['questions']],
            'offers': [project(offer, OFFER_FIELDS) for offer in value['offers']]}


def api(c, app, path, body=None, token=None, method=None, status=200):
    result = request(app, path, body, token, method)
    c.require(result['status'] == status, f'{method or ("GET" if body is None else "POST")} {path}: expected {status}, received {result["status"]}')
    if status >= 400:
        c.require(result['body'].get('error') == {400: 'invalid_request', 401: 'unauthenticated', 403: 'forbidden', 404: 'not_found', 409: 'conflict'}[status], 'Declared error category')
    return result['body']


def tokens(app): return {u['id']: login(app, u['username'], u['password']) for u in app.seed['users']}
def user(app, key): return next(u for u in app.seed['users'] if u['id'] == key)
def detail(c, app, token, listing='listing-a'): return api(c, app, '/api/listings/' + listing, token=token)
def offer(c, app, token, amount=7000, listing='listing-a'):
    return api(c, app, '/api/listings/' + listing + '/offers', {'amount_cents': amount}, token, status=201)['offer']
def counter(c, app, token, item, amount=6500, version=0, status=200):
    return api(c, app, '/api/offers/' + quote(item['id'], safe='') + '/counter', {'amount_cents': amount, 'version': version}, token, status=status)
def accept(c, app, token, item, version=1, status=200, **extra):
    return api(c, app, '/api/offers/' + quote(item['id'], safe='') + '/accept', {'version': version, **extra}, token, status=status)
def price(c, app, token, amount, revision, listing='listing-a', status=200, **extra):
    return api(c, app, '/api/listings/' + listing + '/price', {'price_cents': amount, 'revision': revision, **extra}, token, 'PATCH', status)
def visible_money(page, selector, amount): page.wait_for_function(MONEY_VISIBLE, arg={'selector': selector, 'amount': amount})
def select(page, key='listing-a'):
    page.locator('[data-listing-id=' + json.dumps(key) + ']').click()
    expect(page.locator('#listing-detail')).to_be_visible()


def held_request(page, pattern):
    held = []
    page.evaluate('window.benchmarkHeld = 0')
    def hold(route):
        if held:
            route.continue_(); return
        held.append((route, route.fetch()))
        page.evaluate('window.benchmarkHeld++')
    page.route(pattern, hold)
    return held, hold


def release(held):
    route, response = held[0]
    try: route.fulfill(response=response)
    except BrowserError:
        # Cancelling an obsolete browser request is a valid way to avoid stale data.
        if route.request.failure is None: raise


def gate_one(c):
    with Application() as app:
        t = tokens(app)
        catalog = api(c, app, '/api/catalog', token=t['buyer-a'])
        c.require([row['id'] for row in catalog['listings']] == [row['id'] for row in app.seed['listings']], 'Fixture order and all public listings')
        c.require(catalog['now'] == 2000000000 and catalog['user']['id'] == 'buyer-a', 'Current prepared clock and actual session user')
        for seed, row in zip(app.seed['listings'], catalog['listings']):
            c.require(all(row[key] == value for key, value in seed.items()) and row['revision'] == 0 and row['status'] == 'active', 'Exact fresh synthetic listing values')
        for path, method in [('/api/catalog', 'GET'), ('/api/agreements', 'GET'), ('/api/listings/listing-a', 'GET')]:
            api(c, app, path, token='invalid-session', method=method, status=401)
        api(c, app, '/api/not-a-route', token=t['buyer-a'], status=404)
        api(c, app, '/api/catalog', {}, t['buyer-a'], status=404)
        a = offer(c, app, t['buyer-a']); b = offer(c, app, t['buyer-b'], 6000)
        expected = {'seller-a': {a['id'], b['id']}, 'seller-b': set(), 'buyer-a': {a['id']}, 'buyer-b': {b['id']}}
        for actor, ids in expected.items():
            value = detail(c, app, t[actor])
            c.require({row['id'] for row in value['offers']} == ids, 'Own offer visibility: ' + actor)
            output = json.dumps(value)
            c.require(not any(u['password'] in output for u in app.seed['users']), 'No fixture passwords in detail')
        for actor in ['buyer-b', 'seller-b']:
            counter(c, app, t[actor], a, status=404)
            accept(c, app, t[actor], a, status=404)
        before = snapshot(detail(c, app, t['seller-a']))
        second = login(app, user(app, 'buyer-a')['username'], user(app, 'buyer-a')['password'])
        c.require(second != t['buyer-a'], 'Distinct login sessions')
        api(c, app, '/api/logout', {}, t['buyer-a'])
        api(c, app, '/api/catalog', token=t['buyer-a'], status=401)
        api(c, app, '/api/catalog', token=second)
        app.stop(); app.start(); t = tokens(app)
        c.require(snapshot(detail(c, app, t['seller-a'])) == before, 'Restart retains domain records without reinitialization')
        with browser_session() as browser:
            page = browser.new_page(); page_login(page, app, user(app, 'buyer-a')); select(page)
            expect(page.locator('[data-offer-id]')).to_have_count(1)
            page.reload(); expect(page.locator('#workspace')).to_be_hidden()
            # Only public client observables; no token or private request sequence assumptions.
            page.evaluate("async () => {const {MarketplaceClient}=await import('/app.js');window.probe=new MarketplaceClient();}")
            ua, ub = user(app, 'buyer-a'), user(app, 'buyer-b')
            page.evaluate('(u) => probe.login(u.username,u.password)', ua)
            held, handler = held_request(page, '**/api/catalog')
            page.evaluate('() => {window.oldFlight=probe.refresh();}')
            page.wait_for_function('benchmarkHeld === 1')
            page.evaluate('(u) => probe.login(u.username,u.password)', ub)
            release(held); page.evaluate('() => Promise.resolve(oldFlight).catch(() => null)'); page.unroute('**/api/catalog', handler)
            c.require(page.evaluate('probe.catalog.user.id') == 'buyer-b', 'A late prior-account catalog cannot replace current identity')
            page.route('**/api/catalog', lambda route: route.fulfill(status=401, content_type='application/json', body='{"error":"unauthenticated"}'))
            page.evaluate('() => Promise.resolve(probe.refresh()).catch(() => null)')
            c.require(page.evaluate('probe.catalog === null && probe.detail === null && probe.agreements.length === 0 && Boolean(probe.error)'), 'Current 401 clears private client data')
            page.evaluate('() => probe.dispose()'); page.close()


def gate_two(c):
    with Application() as app:
        t = tokens(app); base = '/api/listings/listing-a'
        originals = ['  Line One\n  Line two  ', '<img src=x onerror=alert(1)>', 'a' * 500]
        for text in originals:
            q = api(c, app, base + '/questions', {'text': text, 'author': {'id': 'seller-b'}, 'listing_id': 'listing-b'}, t['buyer-a'], status=201)['question']
            c.require(q['text'] == text.strip() and q['listing_id'] == 'listing-a' and q['author']['id'] == 'buyer-a', 'Question normalization and session-derived linkage')
        q = detail(c, app, t['seller-b'])['questions']
        c.require([row['text'] for row in q] == [text.strip() for text in originals], 'Questions public to authenticated users in append order')
        first = offer(c, app, t['buyer-a'], 1); second = offer(c, app, t['buyer-a'], 1)
        c.require(first['id'] != second['id'], 'Separate initial offers are not silently deduplicated')
        offer(c, app, t['buyer-a'], 9000)
        before = snapshot(detail(c, app, t['seller-a']))
        for text in ['', '   ', 'a' * 501, None, True, 7, []]:
            api(c, app, base + '/questions', {'text': text}, t['buyer-a'], status=400)
        for amount in [0, -1, 9001, 10000001, True, 1.5, '123', None]:
            api(c, app, base + '/offers', {'amount_cents': amount}, t['buyer-a'], status=400)
        for suffix, body in [('questions', {'text': 'valid'}), ('offers', {'amount_cents': 1})]:
            api(c, app, base + '/' + suffix, body, t['seller-a'], status=403)
            api(c, app, '/api/listings/absent/' + suffix, body, t['buyer-a'], status=404)
            for raw in [b'[]', b'null', b'{', b'{"amount_cents":NaN}', b'{}']:
                api(c, app, base + '/' + suffix, raw, t['buyer-a'], status=400)
        c.require(snapshot(detail(c, app, t['seller-a'])) == before, 'Invalid questions and offers preserve state')
    c.require(public_regressions()['passed'], 'Actual browser visible question/offer controls, literal text, restart and responsive layout')


def gate_three(c):
    fixture = json.loads(Path('/public_tests/catalog.json').read_text())
    # Independent tabulated boundary cases: positive/negative value threshold, inclusive time endpoints and null history.
    cases = [
        (9000, 10000, 9500, 2000000000, ['great_value', 'recently_listed', 'just_reduced']),
        (9001, 10000, 9001, 1999395200, ['recently_listed']),
        (8999999, 10000000, None, 1999395199, ['great_value']),
        (9000001, 10000000, 9000002, 2000000001, ['just_reduced']),
        (1, None, None, 0, []),
        (999, 1111, 998, 2000000000, ['great_value', 'recently_listed']),
        (1000, 1111, 1001, 2000000000, ['recently_listed', 'just_reduced'])]
    fixture['listings'] = [{'id': 'case-' + str(i), 'seller_id': 'seller-a', 'title': 'Synthetic boundary listing ' + str(i),
        'price_cents': p, 'reference_price_cents': r, 'previous_price_cents': previous, 'created_at': created}
        for i, (p, r, previous, created, expected) in enumerate(cases)]
    with Application(fixture=fixture) as app:
        t = tokens(app)
        catalog = api(c, app, '/api/catalog', token=t['buyer-a'])
        for i, case in enumerate(cases):
            c.require(catalog['listings'][i]['labels'] == case[-1], 'Exact ordered labels at boundary ' + str(i))
            c.require(detail(c, app, t['buyer-a'], 'case-' + str(i))['listing']['labels'] == case[-1], 'Detail agrees with live catalog labels')
        app.set_clock(2000604801)
        c.require(detail(c, app, t['buyer-a'], 'case-0')['listing']['labels'] == ['great_value', 'just_reduced'], 'Clock advance removes old recent label without restart')
        app.set_clock(2000000000)
        changed = price(c, app, t['seller-a'], 9500, 0, 'case-0')['listing']
        c.require(changed['labels'] == ['recently_listed'], 'Mutation listing response recomputes labels after price increase')
        with browser_session() as browser:
            page = browser.new_page(); page_login(page, app, user(app, 'buyer-a')); select(page, 'case-1')
            expect(page.locator('#listing-labels [data-label]')).to_have_count(1)
            c.require(page.locator('#listing-labels [data-label]').get_attribute('data-label') == 'recently_listed', 'Selected listing shows returned label')
            c.require(page.locator('#catalog [data-label="great_value"]').count() == 2, 'Catalog renders labels for actual listings')
            app.set_clock(2000604801); page.locator('#refresh').click()
            expect(page.locator('#listing-labels [data-label]')).to_have_count(0)
            expect(page.locator('#catalog [data-label="recently_listed"]')).to_have_count(1)
            c.require(True, 'Refresh removes obsolete catalog labels and includes newly recent future listing')
            page.close()


def gate_four(c):
    with Application() as app:
        t = tokens(app); initial = detail(c, app, t['seller-a'])
        offer(c, app, t['buyer-a']); untouched = snapshot(detail(c, app, t['seller-b'], 'listing-b'))
        updated = api(c, app, '/api/listings/listing-a/price', {'price_cents': 8500, 'revision': 0, 'previous_price_cents': 1, 'reference_price_cents': 1, 'status': 'sold', 'seller_id': 'seller-b'}, t['seller-a'], 'PATCH')['listing']
        c.require(updated['price_cents'] == 8500 and updated['previous_price_cents'] == 9000 and updated['revision'] == 1, 'Price edit saves actual previous price and increments revision once')
        for key in ['reference_price_cents', 'seller_id', 'created_at', 'status']:
            c.require(updated[key] == initial['listing'][key], 'Ignored caller override: ' + key)
        before = snapshot(detail(c, app, t['seller-a']))
        same = price(c, app, t['seller-a'], 8500, 1)['listing']
        c.require(project(same, LISTING_FIELDS) == before['listing'], 'Same-price edit preserves previous price and revision')
        price(c, app, t['seller-a'], 8500, 0, status=409)
        price(c, app, t['buyer-a'], 8000, 1, status=403)
        price(c, app, t['seller-b'], 8000, 1, status=403)
        for amount, revision in [(True, 1), (0, 1), (10000001, 1), (8000, True), (8000, -1), (8000, 1.0), (8000, '1')]:
            price(c, app, t['seller-a'], amount, revision, status=400)
        c.require(snapshot(detail(c, app, t['seller-a'])) == before, 'Rejected edits preserve all listing records')
        price(c, app, t['seller-a'], 10000000, 1)
        value = price(c, app, t['seller-a'], 1, 2)['listing']
        c.require(value['previous_price_cents'] == 10000000 and value['revision'] == 3, 'Both valid money endpoints and rolling price history')
        c.require(snapshot(detail(c, app, t['seller-b'], 'listing-b')) == untouched, 'Price updates do not mutate unrelated listings')
    with Application() as app, browser_session() as browser:
        t = tokens(app); page = browser.new_page(); page_login(page, app, user(app, 'seller-a')); select(page)
        price(c, app, t['seller-a'], 8400, 0)
        page.locator('#new-price').fill('8200'); page.locator('#save-price').click()
        expect(page.locator('#error')).not_to_have_text(''); visible_money(page, '#listing-price', 8400)
        c.require(detail(c, app, t['seller-a'])['listing']['price_cents'] == 8400, 'Browser sends last-read revision and preserves conflicting server price')
        page.locator('#new-price').fill('8200'); page.locator('#save-price').click()
        visible_money(page, '#listing-price', 8200); expect(page.locator('#error')).to_have_text('')
        c.require(detail(c, app, t['seller-a'])['listing']['revision'] == 2, 'Intentional browser retry uses refreshed revision')
        page.close()


def gate_five(c):
    with Application() as app:
        t = tokens(app); a = offer(c, app, t['buyer-a']); b = offer(c, app, t['buyer-b'], 7500)
        untouched = project(b, OFFER_FIELDS)
        price(c, app, t['seller-a'], 6600, 0)
        counter(c, app, t['seller-a'], a, 6601, status=400)
        counter(c, app, t['buyer-a'], a, status=403)
        for actor in ['buyer-b', 'seller-b']: counter(c, app, t[actor], a, status=404)
        for version in [True, -1, 0.0, '0', None]: counter(c, app, t['seller-a'], a, version=version, status=400)
        for amount in [0, True, 10000001, 1.25, '123', None]: counter(c, app, t['seller-a'], a, amount, status=400)
        counter(c, app, t['seller-a'], a, version=9, status=409)
        result = counter(c, app, t['seller-a'], a, 6500)['offer']
        c.require(result['status'] == 'countered' and result['version'] == 1 and result['counter_amount_cents'] == 6500, 'Counter below initial amount accepted at current asking cap')
        c.require(result['amount_cents'] == 7000 and result['buyer_id'] == 'buyer-a', 'Counter preserves buyer and initial offer')
        counter(c, app, t['seller-a'], a, 6400, version=1, status=409)
        after = detail(c, app, t['seller-a'])
        c.require(project(next(o for o in after['offers'] if o['id'] == b['id']), OFFER_FIELDS) == untouched, 'Counter changes only targeted offer')
        c.require(next(o for o in after['offers'] if o['id'] == a['id'])['counter_amount_cents'] == 6500, 'Second counter cannot overwrite issued counter')
        price(c, app, t['seller-a'], 6000, 1)
        c.require(detail(c, app, t['buyer-a'])['offers'][0]['counter_amount_cents'] == 6500, 'Later asking price does not rewrite issued counter')
        equal = offer(c, app, t['buyer-a'], 5900)
        c.require(counter(c, app, t['seller-a'], equal, 5900)['offer']['counter_amount_cents'] == 5900, 'Counter equal to initial offer is valid')
        maximum = offer(c, app, t['buyer-a'], 5000)
        c.require(counter(c, app, t['seller-a'], maximum, 6000)['offer']['counter_amount_cents'] == 6000, 'Counter equal to current asking price is valid')
    with Application() as app, browser_session() as browser:
        t = tokens(app); a = offer(c, app, t['buyer-a'])
        page = browser.new_page(); page_login(page, app, user(app, 'seller-a')); select(page)
        row = page.locator('[data-offer-id]'); row.locator('[data-counter-amount]').fill('6200')
        counter(c, app, t['seller-a'], a, 6400)
        row.locator('[data-counter]').click()
        expect(page.locator('#error')).not_to_have_text(''); visible_money(page, '[data-offer-id]', 6400)
        c.require(detail(c, app, t['buyer-a'])['offers'][0]['counter_amount_cents'] == 6400, 'Seller browser refreshes conflicting counter and reports error')
        page.close()


def gate_six(c):
    with Application() as app:
        t = tokens(app)
        api(c, app, '/api/listings/listing-a/questions', {'text': 'Preserve this question'}, t['buyer-a'], status=201)
        a = offer(c, app, t['buyer-a']); b = offer(c, app, t['buyer-b'], 7200); pending = offer(c, app, t['buyer-a'], 6100)
        unrelated = offer(c, app, t['buyer-b'], 5000, 'listing-b')
        counter(c, app, t['seller-a'], a, 6500); counter(c, app, t['seller-a'], b, 6300)
        price(c, app, t['seller-a'], 6000, 0)
        before = snapshot(detail(c, app, t['seller-a']))
        accept(c, app, t['seller-a'], a, status=403)
        accept(c, app, t['buyer-b'], a, status=404)
        accept(c, app, t['buyer-a'], pending, version=0, status=409)
        accept(c, app, t['buyer-a'], a, version=0, status=409)
        for version in [True, -1, 1.0, '1', None]: accept(c, app, t['buyer-a'], a, version=version, status=400)
        c.require(snapshot(detail(c, app, t['seller-a'])) == before, 'Rejected accepts leave no partial domain transition')
        def compete(pair):
            item, token = pair
            return request(app, '/api/offers/' + quote(item['id'], safe='') + '/accept', {'version': 1, 'amount_cents': 1, 'buyer_id': 'seller-b'}, token)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(compete, [(a, t['buyer-a']), (b, t['buyer-b'])]))
        c.require(sorted(r['status'] for r in results) == [200, 409], 'Concurrent competing accepts have exactly one successful transaction')
        index = next(i for i, r in enumerate(results) if r['status'] == 200)
        winner, buyer_id, agreed = [(a, 'buyer-a', 6500), (b, 'buyer-b', 6300)][index]
        outcome = results[index]['body']; agreement = project(outcome['agreement'], AGREEMENT_FIELDS)
        c.require(agreement['amount_cents'] == agreed and agreement['buyer_id'] == buyer_id and agreement['seller_id'] == 'seller-a' and agreement['offer_id'] == winner['id'], 'Agreement uses stored counter and actual parties despite later asking-price edit')
        after = detail(c, app, t['seller-a'])
        c.require(after['listing']['status'] == 'sold' and after['listing']['revision'] == 2 and after['listing']['labels'] == [], 'Single committed sale increments listing revision and removes labels')
        c.require(snapshot(after)['questions'] == before['questions'], 'Sale preserves questions')
        for item in after['offers']:
            expected_status = 'accepted' if item['id'] == winner['id'] else 'closed'
            expected_version = 1 if item['id'] == pending['id'] else 2
            c.require(item['status'] == expected_status and item['version'] == expected_version, 'Atomic competing-offer closure and one version increment')
        c.require(project(detail(c, app, t['buyer-b'], 'listing-b')['offers'][0], OFFER_FIELDS) == project(unrelated, OFFER_FIELDS), 'Sale preserves unrelated listing offers')
        for actor in ['seller-a', buyer_id]:
            rows = api(c, app, '/api/agreements', token=t[actor])['agreements']
            c.require(len(rows) == 1 and project(rows[0], AGREEMENT_FIELDS) == agreement, 'Exactly one persisted agreement visible to each party')
        for actor in ['seller-b', 'buyer-b' if buyer_id == 'buyer-a' else 'buyer-a']:
            c.require(api(c, app, '/api/agreements', token=t[actor])['agreements'] == [], 'Unrelated users cannot read agreement')
        for suffix, body in [('questions', {'text': 'Late question'}), ('offers', {'amount_cents': 1})]:
            api(c, app, '/api/listings/listing-a/' + suffix, body, t[buyer_id], status=409)
        price(c, app, t['seller-a'], 5500, 2, status=409)
        counter(c, app, t['seller-a'], pending, 1, version=1, status=409)
        replay = accept(c, app, t[buyer_id], winner, version=0)
        c.require(project(replay['agreement'], AGREEMENT_FIELDS) == agreement and snapshot(detail(c, app, t['seller-a'])) == snapshot(after), 'Stale successful accept replay causes no extra mutation')
        accept(c, app, t[buyer_id], winner, version=True, status=400)
        app.stop(); app.start(); t = tokens(app)
        replay = accept(c, app, t[buyer_id], winner, version=99)
        c.require(project(replay['agreement'], AGREEMENT_FIELDS) == agreement and snapshot(detail(c, app, t['seller-a'])) == snapshot(after), 'Successful replay and all committed state survive restart')
    with Application() as app, browser_session() as browser:
        t = tokens(app)
        buyer = browser.new_page(viewport={'width': 390, 'height': 844}); seller = browser.new_page()
        page_login(buyer, app, user(app, 'buyer-a')); select(buyer)
        buyer.locator('#offer-amount').fill('7100'); buyer.locator('#place-offer').click(); expect(buyer.locator('[data-offer-id]')).to_have_count(1)
        page_login(seller, app, user(app, 'seller-a')); select(seller)
        seller.locator('[data-counter-amount]').fill('6700'); seller.locator('[data-counter]').click()
        expect(seller.locator('#offers')).to_contain_text(re.compile(r'(?:countered|counter[ -]?offer)',re.I))
        buyer.locator('#refresh').click(); buyer.locator('[data-accept]').click()
        expect(buyer.locator('#listing-status')).to_contain_text(re.compile(r'\b(?:sold|sale completed)\b',re.I)); visible_money(buyer, '#agreements', 6700)
        c.require('listing-a' in buyer.locator('#agreements').inner_text(), 'Browser displays persisted agreement listing')
        expect(buyer.locator('#listing-labels [data-label]')).to_have_count(0)
        seller.locator('#refresh').click(); expect(seller.locator('#listing-status')).to_contain_text(re.compile(r'\b(?:sold|sale completed)\b',re.I)); visible_money(seller, '#agreements', 6700)
        # Exercise the public controller with a delayed real mutation response.
        buyer.evaluate("async()=>{const {MarketplaceClient}=await import('/app.js');window.probe=new MarketplaceClient();}")
        buyer.evaluate('(u)=>probe.login(u.username,u.password)', user(app, 'buyer-a'))
        buyer.evaluate('()=>probe.openListing("listing-c")')
        buyer.evaluate('()=>probe.offer(2000)')
        # Public methods may return no payload; observe the offer through the declared detail state.
        item = buyer.evaluate('probe.detail.offers[0]')
        counter(c, app, t['seller-a'], item, 2500)
        buyer.evaluate('()=>probe.refresh()')
        held, handler = held_request(buyer, '**/api/offers/*/accept')
        buyer.evaluate('(id)=>{window.pendingAccept=probe.accept(id);}', item['id'])
        buyer.wait_for_function('benchmarkHeld===1')
        buyer.evaluate('()=>probe.openListing("listing-b")')
        release(held); buyer.evaluate('()=>Promise.resolve(pendingAccept).catch(() => null)'); buyer.unroute('**/api/offers/*/accept', handler)
        c.require(buyer.evaluate('probe.detail.listing.id') == 'listing-b', 'Late accept cannot overwrite a newer listing selection')
        buyer.evaluate('()=>probe.dispose()'); buyer.close(); seller.close()


GATES = [gate_one, gate_two, gate_three, gate_four, gate_five, gate_six]


def main():
    results, errors = [], []
    for index, gate in enumerate(GATES, 1):
        c = Checks(); row = {'ru_id': f'RU-{index:03d}', 'passed': False}
        try:
            gate(c); row.update(passed=True, detail='All executable checks passed')
        except (AssertionError, KeyError, TypeError, IndexError, ValueError, StopIteration, BrowserTimeout) as error:
            row['detail'] = type(error).__name__ + ': ' + str(error)
        except Exception as error:
            row['detail'] = 'Unattributed evaluator/environment error: ' + repr(error)
            errors.append({'ru_id': row['ru_id'], 'traceback': traceback.format_exc()})
        row['checks_passed'] = c.passed; results.append(row)
    print(json.dumps({'harness_ok': not errors, 'results': results, 'infrastructure_errors': errors}))
    return 0 if not errors else 2


if __name__ == '__main__': raise SystemExit(main())
