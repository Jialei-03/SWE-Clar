"""Disclosed arena foundation; no hidden protection duration or replay rules."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from arena_support import Application, browser_session, request
from playwright.sync_api import expect


def fixture():
    return {'rooms': [
        {'id': 'public-a', 'label': 'Synthetic test arena A', 'cols': 12, 'rows': 8,
         'walls': [[2, 2], [7, 3]], 'spawn_points': [[2, 3], [4, 3], [2, 6]]},
        {'id': 'public-b', 'label': 'Synthetic test arena B', 'cols': 10, 'rows': 8,
         'walls': [[5, 4]], 'spawn_points': [[2, 3], [4, 3]]}]}


def call(app, path, body=None, token=None, status=200):
    result = request(app, path, body, token)
    assert result['status'] == status, (path, result)
    return result['body']


def main():
    checks = []
    with Application(world=fixture(), now_ms=100000) as app:
        call(app, '/api/state', status=401)
        call(app, '/api/join', {'room_id': 'missing', 'label': 'Synthetic'}, status=404)
        call(app, '/api/join', {'room_id': 'public-a', 'label': '  '}, status=400)
        a = call(app, '/api/join', {'room_id': 'public-a', 'label': 'Synthetic One', 'x': 9, 'hp': 99}, status=201)
        b = call(app, '/api/join', {'room_id': 'public-a', 'label': 'Synthetic Two'}, status=201)
        foreign = call(app, '/api/join', {'room_id': 'public-b', 'label': 'Synthetic Other'}, status=201)
        own = next(p for p in a['state']['players'] if p['id'] == a['player_id'])
        assert (own['x'], own['y'], own['hp'], own['generation'], own['alive']) == (2, 3, 3, 1, True)
        other = call(app, '/api/state?room_id=public-a', token=foreign['token'])['state']
        assert other['room']['id'] == 'public-b' and len(other['players']) == 1
        assert all(token not in json.dumps(other) for token in [a['token'], b['token'], foreign['token']])
        # Exercise normal unprotected behavior without prescribing a duration.
        app.set_clock(max(p['protected_until_ms'] for p in b['state']['players']) + 1)
        def move(command, direction):
            return call(app, '/api/move', {'generation': 1, 'command_id': command, 'direction': direction,
                                         'player_id': b['player_id'], 'room_id': 'public-b'}, a['token'])['state']
        state = move('wall', 'up'); own = next(p for p in state['players'] if p['id'] == a['player_id'])
        assert (own['x'], own['y'], own['hp']) == (2, 3, 3)
        move('open-cell', 'right')
        for n in range(3):
            state = move('contact-' + str(n), 'right')
        own = next(p for p in state['players'] if p['id'] == a['player_id'])
        target = next(p for p in state['players'] if p['id'] == b['player_id'])
        assert (own['x'], own['y'], own['hp'], own['alive']) == (3, 3, 0, False)
        assert (target['x'], target['y'], target['hp']) == (4, 3, 3)
        call(app, '/api/move', {'generation': True, 'command_id': 'bad', 'direction': 'up'}, a['token'], 400)
        call(app, '/api/leave', {}, a['token'])
        call(app, '/api/state', token=a['token'], status=401)
        assert len(call(app, '/api/state', token=b['token'])['state']['players']) == 1
        checks.extend(['Real sessions and room isolation', 'Authoritative joining, walls, movement and contact/death', 'Independent leave invalidation'])
    with Application(world=fixture(), now_ms=200000) as app, browser_session() as browser:
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        first, second = context.new_page(), context.new_page()
        errors = []
        first.on('pageerror', lambda error: errors.append(str(error)))
        accounts = []
        for page, label in [(first, 'Synthetic <b>literal</b>'), (second, 'Synthetic Observer')]:
            page.goto(app.url)
            page.locator('#player-label').fill(label)
            with page.expect_response('**/api/join') as joined:
                page.locator('#join').click()
            accounts.append(joined.value.json())
            expect(page.locator('#game')).to_be_visible()
        expect(first.locator('#roster [data-player-id]')).to_have_count(2)
        assert first.locator('#roster b').count() == 0
        expect(first.locator('#roster')).to_contain_text('Synthetic <b>literal</b>')
        app.set_clock(max(p['protected_until_ms'] for p in accounts[-1]['state']['players']) + 1)
        first.wait_for_timeout(250)
        before = second.locator('#arena').screenshot()
        first.locator('[data-direction="down"]').click()
        first.wait_for_timeout(300)
        state = call(app, '/api/state', token=accounts[0]['token'])['state']
        own = next(p for p in state['players'] if p['id'] == accounts[0]['player_id'])
        assert (own['x'], own['y']) == (2, 4)
        assert second.locator('#arena').screenshot() != before
        for width, height in [(1280, 900), (390, 844)]:
            first.set_viewport_size({'width': width, 'height': height})
            assert first.evaluate('document.documentElement.scrollWidth<=innerWidth')
        first.locator('#leave').click()
        expect(first.locator('#game')).to_be_hidden()
        assert first.locator('#roster').inner_text() == '' and not errors, errors
        context.close()
        checks.extend(['Actual two-player browser canvas and command flow', 'Literal labels, responsive viewport and cleared UI'])
    print(json.dumps({'passed': True, 'public_regressions': checks, 'hidden_rule_answers_in_public_tests': False}))


if __name__ == '__main__':
    main()
