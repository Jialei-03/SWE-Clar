"""Visible regressions: profiles, actual PNGs, waypoints, ordered routes and map."""
import json
from io import BytesIO
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.sync_api import expect, Error as BrowserError
from route_support import Application, browser_session
from fixtures import sample_png
from PIL import Image


def photo_visible(page, selector):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try: pixels = page.locator(selector).screenshot()
        except BrowserError as error:
            if 'Element is not attached to the DOM' not in str(error): raise
            page.wait_for_timeout(50); continue
        with Image.open(BytesIO(pixels)) as image:
            colors = image.convert('RGB').getdata()
            if sum(all(abs(value - expected) <= 12 for value, expected in zip(pixel, (48, 120, 88))) for pixel in colors) >= 4:
                return
        page.wait_for_timeout(50)
    raise AssertionError('Uploaded photo pixels were not visibly rendered')


def run():
    with Application() as app, browser_session() as browser:
        page = browser.new_page(viewport={'width': 390, 'height': 844}); page.goto(app.url)
        user = app.seed['users'][0]
        page.locator('#username').fill(user['username']); page.locator('#password').fill(user['password']); page.locator('#login').click()
        expect(page.locator('#workspace')).to_be_visible()
        page.locator('#upload-file').set_input_files({'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': sample_png()})
        page.locator('#upload-photo').click(); expect(page.locator('#asset-list [data-asset-id]')).to_have_count(1)
        photo = page.locator('#asset-list [data-asset-id]').get_attribute('data-asset-id')
        page.locator('#profile-name').fill('Synthetic Member'); page.locator('#profile-photo').select_option(photo); page.locator('#save-profile').click()
        # The supplied baseline uses actual images; do not score an image ID alone as image rendering.
        photo_visible(page, '#asset-list [data-asset-id]')
        for index, (name, lat, lon) in enumerate([('Stop <b>one</b>', 12, 20), ('Second stop', -14, 27)], 1):
            page.locator('#waypoint-name').fill(name); page.locator('#waypoint-lat').fill(str(lat)); page.locator('#waypoint-lon').fill(str(lon))
            if index == 1: page.locator('#waypoint-photos').select_option(photo)
            page.locator('#create-waypoint').click(); expect(page.locator('#waypoint-list [data-waypoint-id]')).to_have_count(index)
        assert page.locator('#waypoint-photos').evaluate('node=>node.selectedOptions.length') == 0
        assert page.locator('#waypoint-list b').count() == 0
        ids = page.locator('#waypoint-list [data-waypoint-id]').evaluate_all('nodes=>nodes.map(node=>node.dataset.waypointId)')
        page.locator('#route-title').fill('Sample route'); page.locator('#route-waypoints').fill(json.dumps(ids[::-1])); page.locator('#create-route').click()
        expect(page.locator('#route-list [data-route-id]')).to_have_count(1)
        page.locator('#route-list [data-route-id]').click(); expect(page.locator('#route-detail')).to_be_visible()
        assert page.locator('#route-stops [data-stop-id]').evaluate_all('nodes=>nodes.map(node=>node.dataset.stopId)') == ids[::-1]
        expect(page.locator('#map [data-waypoint-id]')).to_have_count(2)
        assert page.locator('#map').screenshot().startswith(b'\x89PNG')
        for width, height in [(390, 844), (1280, 900)]:
            page.set_viewport_size({'width': width, 'height': height}); assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('#logout').click(); expect(page.locator('#workspace')).to_be_hidden(); page.reload(); expect(page.locator('#workspace')).to_be_hidden()
    return {'passed': True, 'scope': 'visible profile/photo/waypoint/ordered-route/map baseline only'}


if __name__ == '__main__': print(json.dumps(run()))
