"""Read integration with a pre-provisioned synthetic offer service."""
import json
import threading
from urllib.error import URLError
from urllib.request import Request, urlopen
from domain import AppError, integer


class Integration:
    def __init__(self, store, service_url):
        self.store, self.service_url = store, service_url.rstrip('/')
        self.lock = threading.RLock()

    def remote(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urlopen(Request(self.service_url + path, data=data, headers={'Content-Type': 'application/json'}), timeout=3) as response:
                return json.loads(response.read())
        except (URLError, TimeoutError, ValueError) as error:
            raise AppError(502, {'provider': 'unavailable or malformed response'}) from error

    def receive(self, events):
        raise AppError(501, {'events': 'offer event handling is unfinished'})

    def sync(self, now, callback_url):
        if not integer(now, 0, 10**12):
            raise AppError(400, {'now': 'nonnegative integer required'})
        self.remote('/health')
        return {'mode': 'unconfigured', 'updated': 0, 'polled': False}
