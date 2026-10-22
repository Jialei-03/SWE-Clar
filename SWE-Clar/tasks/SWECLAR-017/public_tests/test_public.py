"""Public regressions for the prepared catalog, questions and initial offers."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from marketplace_support import Application, browser_session, request

AMOUNT_IN_ROW = r'''(amount) => [...document.querySelectorAll('[data-offer-id]')].some(row =>
  /\b(pending|awaiting (?:a )?response)\b/i.test(row.innerText) && (row.innerText.match(/[+-]?\d[\d,]*(?:\.\d+)?(?:e[+-]?\d+)?/gi) || [])
    .some(value => Number(value.replaceAll(',', '')) === amount))'''


def login(app, username, password):
    response = request(app, '/api/login', {'username': username, 'password': password})
    assert response['status'] == 200, response
    assert isinstance(response['body']['token'], str) and response['body']['token']
    return response['body']['token']


def page_login(page, app, user):
    page.goto(app.url)
    page.locator('#username').fill(user['username'])
    page.locator('#password').fill(user['password'])
    page.locator('#login').click()
    page.wait_for_function("!document.getElementById('workspace').hidden && document.querySelector('[data-listing-id]') !== null")


def run():
    with Application() as app:
        seed = app.seed
        buyer = next(user for user in seed['users'] if user['role'] == 'buyer')
        listing = seed['listings'][0]
        seller = next(user for user in seed['users'] if user['id'] == listing['seller_id'])
        token = login(app, buyer['username'], buyer['password'])
        catalog = request(app, '/api/catalog', token=token)
        assert catalog['status'] == 200
        assert [row['id'] for row in catalog['body']['listings']] == [row['id'] for row in seed['listings']]
        assert catalog['body']['user']['id'] == buyer['id']
        assert request(app, '/api/catalog')['status'] == 401
        path = '/api/listings/' + listing['id']
        text = '  Is the base  removable?  '
        question = request(app, path + '/questions', {'text': text, 'author_id': seller['id']}, token)
        assert question['status'] == 201
        value = question['body']['question']
        assert value['text'] == text.strip() and value['author']['id'] == buyer['id']
        offer = request(app, path + '/offers', {'amount_cents': listing['price_cents'] - 1}, token)
        assert offer['status'] == 201
        value = offer['body']['offer']
        assert value['buyer_id'] == buyer['id'] and value['status'] == 'pending'
        assert value['counter_amount_cents'] is None and value['version'] == 0
        seller_token = login(app, seller['username'], seller['password'])
        assert request(app, path + '/questions', {'text': 'seller question'}, seller_token)['status'] == 403
        for amount in [0, True, 1.5, '100']:
            assert request(app, path + '/offers', {'amount_cents': amount}, token)['status'] == 400
        app.stop(); app.start()
        token = login(app, buyer['username'], buyer['password'])
        detail = request(app, path, token=token)['body']
        assert any(row['id'] == question['body']['question']['id'] for row in detail['questions'])
        assert any(row['id'] == offer['body']['offer']['id'] for row in detail['offers'])
        with browser_session() as browser:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page_login(page, app, buyer)
            page.locator('[data-listing-id]').filter(has_text=listing['title']).click()
            page.wait_for_function("!document.getElementById('listing-detail').hidden")
            marker = 'Does <b>this</b> stay literal?'
            page.locator('#question-text').fill(marker); page.locator('#ask').click()
            page.wait_for_function('(text) => document.getElementById("questions").textContent.includes(text)', arg=marker)
            assert page.locator('#questions b').count() == 0
            amount = listing['price_cents'] - 2
            page.locator('#offer-amount').fill(str(amount)); page.locator('#place-offer').click()
            page.wait_for_function(AMOUNT_IN_ROW, arg=amount)
            for width, height in [(390, 844), (1280, 900)]:
                page.set_viewport_size({'width': width, 'height': height})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.locator('#logout').click()
            page.wait_for_function('document.getElementById("workspace").hidden')
            assert marker not in page.locator('body').inner_text()
            page.reload()
            assert page.locator('#workspace').is_hidden()
            page.close()
    return {'passed': True, 'scope': 'visible catalog/questions/initial offers and actual browser; no hidden business thresholds'}


if __name__ == '__main__':
    print(json.dumps(run()))
