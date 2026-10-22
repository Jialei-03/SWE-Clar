"""Real local provider HTTP transport; credentials stay out of returned data."""
import json
from urllib.request import Request, urlopen


class Provider:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip('/')
        self.token = token

    def request(self, route, body):
        encoded = json.dumps(body, allow_nan=False).encode('utf-8')
        request = Request(self.base_url + route, data=encoded,
                          headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise ValueError('Provider status failure')
            data = response.read(1048577)
            if len(data) > 1048576:
                raise ValueError('Provider response too large')
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError('Provider response must be an object')
        return value
