"""HTTP integration with the prepared loopback offer service."""
import json
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from domain import AppError, integer


class Integration:
    def __init__(self, store, service_url):
        self.store = store
        self.service_url = service_url.rstrip('/')
        # A sync and a callback in this process must not race their checkpoint
        # decisions.  SQLite still provides the durable cross-process guard.
        self.lock = threading.RLock()

    def remote(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        method = 'POST' if body is not None else 'GET'
        try:
            request = Request(
                self.service_url + path,
                data=data,
                method=method,
                headers={'Content-Type': 'application/json'} if body is not None else {},
            )
            with urlopen(request, timeout=3) as response:
                if response.status != 200:
                    raise ValueError('provider status')
                value = json.loads(response.read())
                if not isinstance(value, dict):
                    raise ValueError('provider object required')
                return value
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise AppError(502, {'provider': 'unavailable or malformed response'}) from error

    @staticmethod
    def _provider_error():
        return AppError(502, {'provider': 'unavailable or malformed response'})

    def _subscribe(self, callback_url):
        response = self.remote('/subscriptions', {'callback_url': callback_url})
        if response.get('subscribed') is not True:
            raise self._provider_error()

    @staticmethod
    def _validate_poll_response(response, previous_cursor):
        if not isinstance(response, dict):
            raise Integration._provider_error()
        events = response.get('events')
        cursor = response.get('cursor')
        if not isinstance(events, list) or not integer(cursor, 0, 10 ** 12):
            raise Integration._provider_error()
        if not integer(previous_cursor, 0, 10 ** 12) or cursor < previous_cursor:
            raise Integration._provider_error()

        previous = previous_cursor
        for event in events:
            if not isinstance(event, dict):
                raise Integration._provider_error()
            event_cursor = event.get('cursor')
            if (
                not integer(event_cursor, 1, 10 ** 12)
                or event_cursor <= previous
                or event_cursor > cursor
            ):
                raise Integration._provider_error()
            previous = event_cursor
        return events, cursor

    def receive(self, events):
        # This route is a simulated provider callback, not a user route, so it
        # intentionally has no X-Actor requirement.
        with self.lock:
            if not isinstance(events, list):
                raise AppError(400, {'events': 'list required'})
            updated = self.store.receive_events(events)
            return {'updated': updated}

    def sync(self, now, callback_url):
        if not integer(now, 0, 10 ** 12):
            raise AppError(400, {'now': 'nonnegative integer required'})

        with self.lock:
            state = self.store.integration_state()
            mode = state['mode']
            cursor = state['cursor']

            if mode is None:
                # Capabilities are consulted exactly for the first successful
                # setup.  A failed capability read or failed first poll does
                # not leave a mode checkpoint behind, allowing a retry.
                capabilities = self.remote('/capabilities')
                webhook_supported = capabilities.get('webhook_supported')
                if type(webhook_supported) is not bool:
                    raise self._provider_error()

                if webhook_supported:
                    self._subscribe(callback_url)
                    self.store.set_webhook(callback_url)
                    return {'mode': 'webhook', 'updated': 0, 'polled': False}

                # The first polling setup always starts at the provider's
                # beginning, as opposed to relying on a not-yet-established
                # poll checkpoint.
                response = self.remote('/offers?after=0')
                try:
                    events, response_cursor = self._validate_poll_response(response, 0)
                    updated = self.store.commit_poll(events, response_cursor, now)
                except AppError as error:
                    if error.status == 502:
                        raise
                    raise self._provider_error() from error
                return {'mode': 'poll', 'updated': updated, 'polled': True}

            if mode == 'webhook':
                # The provider is a single-consumer fixture.  A process
                # restart on a new ephemeral port must bind its new callback;
                # a repeated tick on the same URL must not re-register.
                if state['callback_url'] != callback_url:
                    self._subscribe(callback_url)
                    self.store.set_webhook(callback_url)
                return {'mode': 'webhook', 'updated': 0, 'polled': False}

            if mode != 'poll':
                # This can only arise from a manually corrupted database, but
                # treating it like an unavailable integration avoids exposing
                # internal metadata in an API response.
                raise self._provider_error()

            last_poll = state['last_poll']
            due = last_poll is None or now - last_poll >= 120
            if not due:
                return {'mode': 'poll', 'updated': 0, 'polled': False}

            response = self.remote('/offers?after=' + str(cursor))
            try:
                events, response_cursor = self._validate_poll_response(response, cursor)
                updated = self.store.commit_poll(events, response_cursor, now)
            except AppError as error:
                if error.status == 502:
                    raise
                raise self._provider_error() from error
            return {'mode': 'poll', 'updated': updated, 'polled': True}
