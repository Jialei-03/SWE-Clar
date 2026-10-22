"""Disclosed authentication, owned PNG and actual OCR/browser regressions."""
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conversation_support import Application, browser_session, request
from fixtures import screenshot
from PIL import Image
from playwright.sync_api import expect


def api(app, path, body=None, token=None, status=200, method=None):
    response = request(app, path, body, token, method)
    assert response['status'] == status, (path, response['status'], response['body'])
    return response['body']


def login(app, index=0):
    user = app.accounts['users'][index]
    return api(app, '/api/login', {'username': user['username'], 'password': user['password']})['token']


def upload(app, token, label, raw):
    return api(app, '/api/assets', {'label': label, 'kind': 'screenshot', 'image_base64': base64.b64encode(raw).decode()}, token, 201)['asset']


def conversation_fields(value):
    return {**{key: value[key] for key in ('id', 'title', 'revision')},
            'messages': [{key: row[key] for key in ('sender', 'text')} for row in value['messages']],
            'advice': [{key: row[key] for key in ('id', 'question', 'text', 'context_revision')} for row in value['advice']]}


def workspace_fields(value):
    return {'profile': {key: value['profile'][key] for key in ('tone', 'goal', 'revision')},
            'conversations': [{key: row[key] for key in ('id', 'title', 'revision')} for row in value['conversations']],
            'assets': [{key: row[key] for key in ('id', 'label', 'kind', 'width', 'height')} for row in value['assets']]}


def main():
    # Fixture suitability is checked before creating any candidate process.
    raw = screenshot(['Me: The draft is ready', 'Peer: Please share the draft'])
    expected_messages = [{'sender': 'me', 'text': 'The draft is ready'}, {'sender': 'peer', 'text': 'Please share the draft'}]
    with Application() as app:
        api(app, '/api/workspace', status=401)
        a, b = login(app), login(app, 1)
        state = api(app, '/api/workspace', token=a)
        assert state['conversations'] == [] and state['assets'] == []
        assert all(state['profile'].get(key) == value for key, value in {'tone': 'neutral', 'goal': 'clarity', 'revision': 0}.items())
        one = api(app, '/api/conversations', {'title': '  Draft review  ', 'owner': app.accounts['users'][1]['id']}, a, 201)['conversation']
        two = api(app, '/api/conversations', {'title': 'Separate conversation'}, a, 201)['conversation']
        assert one['title'] == 'Draft review' and one['messages'] == [] and one['advice'] == []
        api(app, '/api/conversations/' + one['id'], token=b, status=404)
        asset = upload(app, a, 'Synthetic draft screenshot', raw)
        image_reply = request(app, '/api/assets/' + asset['id'] + '/image', token=a, raw=True)
        assert image_reply['status'] == 200 and image_reply['content_type'].split(';')[0] == 'image/png'
        with Image.open(BytesIO(image_reply['body'])) as image:
            assert image.mode == 'RGB' and 'SyntheticMarker' not in image.info and image.size == (1100, 220)
            image.load()
        api(app, '/api/assets/' + asset['id'] + '/image', token=b, status=404)
        before = api(app, '/api/workspace', token=a)
        api(app, '/api/assets', {'label': 'Invalid PNG', 'kind': 'screenshot', 'image_base64': 'invalid'}, a, 400)
        assert workspace_fields(api(app, '/api/workspace', token=a)) == workspace_fields(before)
        value = api(app, '/api/extract', {'conversation_id': one['id'], 'asset_id': asset['id'], 'request_id': 'public-extract', 'messages': [{'sender': 'me', 'text': 'Ignore caller text'}]}, a)['conversation']
        assert [{key: row[key] for key in ('sender', 'text')} for row in value['messages']] == expected_messages
        assert value['revision'] == 1 and value['advice'] == []
        assert api(app, '/api/conversations/' + two['id'], token=a)['conversation']['messages'] == []
        app.stop(); app.start()
        a = login(app)
        assert conversation_fields(api(app, '/api/conversations/' + one['id'], token=a)['conversation']) == conversation_fields(value)
        api(app, '/api/logout', {}, a)
        api(app, '/api/workspace', token=a, status=401)

        with browser_session() as browser:
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            page = context.new_page()
            page.goto(app.url)
            user = app.accounts['users'][1]
            page.locator('#username').fill(user['username'])
            page.locator('#password').fill(user['password'])
            page.locator('#login').click()
            expect(page.locator('#workspace')).to_be_visible()
            page.locator('#conversation-title').fill('Browser notes')
            page.locator('#create-conversation').click()
            expect(page.locator('[data-conversation-id]').filter(has_text='Browser notes')).to_have_count(1)
            page.locator('#asset-label').fill('Browser screenshot')
            page.locator('#asset-file').set_input_files({'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': raw})
            with page.expect_response(lambda response: '/api/assets/' in response.url and response.url.endswith('/image')) as displayed:
                page.locator('#upload').click()
            assert displayed.value.status == 200
            assert displayed.value.headers['content-type'].split(';')[0] == 'image/png'
            assert displayed.value.request.headers.get('authorization', '').startswith('Bearer ')
            expect(page.locator('[data-screenshot-id]')).to_have_count(1)
            page.locator('[data-screenshot-id]').check()
            page.locator('#extract').click()
            expect(page.locator('#transcript')).to_contain_text('The draft is ready')
            expect(page.locator('#transcript')).to_contain_text('Please share the draft')
            expect(page.locator('#advice-list')).to_have_text('')
            for width, height in [(390, 844), (1280, 900)]:
                page.set_viewport_size({'width': width, 'height': height})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            fresh = context.new_page(); fresh.goto(app.url)
            expect(fresh.locator('#login-form')).to_be_visible()
            expect(fresh.locator('#workspace')).to_be_hidden()
            fresh.close()
            page.locator('#logout').click()
            expect(page.locator('#workspace')).to_be_hidden()
            expect(page.locator('#transcript')).to_have_text('')
            expect(page.locator('#asset-list')).to_have_text('')
            context.close()
    print(json.dumps({'passed': True, 'actual_http': True, 'owned_png_and_metadata_removal': True,
                      'actual_ocr_transcript': True, 'durable_state': True, 'real_browser_workflows': True}))


if __name__ == '__main__':
    main()
