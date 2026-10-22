"""Disclosed raw integer and real browser regressions only."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lattice_support import Application, browser_session, request
from playwright.sync_api import expect


def main():
    with Application() as app:
        problem = {'total': 8, 'limit': 32, 'family_policy': 'all', 'coordinates': 'raw'}
        r = request(app, '/api/geometry', problem)
        assert r['status'] == 200
        result = r['body']
        assert all(result['problem'].get(k) == v for k, v in problem.items())
        assert [(f['a'], f['b']) for f in result['families']] == [(7, 1), (6, 2), (5, 3)]
        for f in result['families']:
            expected = {}
            for x in range(1, 33):
                for y in range(1, 33):
                    n = f['a'] * x + f['b'] * y
                    if 8 < n <= 32:expected.setdefault(n, []).append([x, y])
            actual = {line['n']: line['points'] for line in f['lines']}
            assert actual == expected
            assert f['point_count'] == sum(map(len, expected.values()))
        assert request(app, '/api/geometry', {**problem, 'total': True})['status'] == 400
        assert request(app, '/api/geometry', {**problem, 'limit': 8})['status'] == 400
        with browser_session() as browser:
            page = browser.new_page(viewport={'width': 390, 'height': 844});page.goto(app.url)
            expect(page.locator('#export')).to_be_disabled()
            blank = page.locator('#plot').screenshot()
            with page.expect_response('**/api/geometry') as response:page.locator('#run').click()
            assert response.value.status == 200
            count = sum(f['point_count'] for f in result['families'])
            expect(page.locator('#result-summary')).to_have_attribute('data-point-count', str(count))
            expect(page.locator('[data-family-key]')).to_have_count(3)
            assert page.locator('#plot').screenshot() != blank
            for width,height in [(390,844),(1280,900)]:
                page.set_viewport_size({'width':width,'height':height})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#total').fill('2');page.locator('#run').click();expect(page.locator('#error')).to_be_visible()
            page.close()
    print(json.dumps({'passed': True, 'actual_http': True, 'complete_raw_integer_solutions': True, 'actual_browser_canvas': True}))


if __name__ == '__main__':main()
