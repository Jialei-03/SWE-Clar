"""Synthetic local offer provider. All events and identities are generated fixtures."""
import argparse
from copy import deepcopy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen
import html


class OfferService:
    def __init__(self, events=(), *, webhook_supported=False, port=0):
        self.events = deepcopy(list(events))
        self.webhook_supported = webhook_supported
        self.requests = []
        self.subscriptions = []
        self.fail_reads = False
        self._lock = threading.RLock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send(self, status, payload, content_type='application/json'):
                body = json.dumps(payload).encode() if content_type == 'application/json' else payload.encode()
                self.send_response(status)
                self.send_header('Content-Type', content_type + '; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parts = urlsplit(self.path)
                with owner._lock:
                    owner.requests.append({'method': 'GET', 'path': self.path})
                    if parts.path == '/health':
                        return self.send(200, {'ready': True})
                    if parts.path == '/capabilities':
                        return self.send(200, {'webhook_supported': owner.webhook_supported})
                    if parts.path == '/offers':
                        query = parse_qs(parts.query)
                        value = query.get('after', ['0'])
                        if len(value) != 1 or not re.fullmatch(r'\d+', value[0]):
                            return self.send(400, {'error': 'invalid_cursor'})
                        if owner.fail_reads:
                            return self.send(503, {'error': 'fixture_read_failure'})
                        after = int(value[0])
                        events = [deepcopy(e) for e in owner.events if e['cursor'] > after]
                        events.sort(key=lambda e: e['cursor'])
                        return self.send(200, {'events': events, 'cursor': max([after, *[e['cursor'] for e in events]])})
                    if parts.path.startswith('/review/'):
                        key = parts.path.removeprefix('/review/')
                        events = [e for e in owner.events if quote(e['external_id'], safe='') == key]
                        if not events:
                            return self.send(404, {'error': 'unknown_offer'})
                        latest = max(events, key=lambda e: e['revision'])
                        text = '<!doctype html><html><head><title>Synthetic offer review</title></head><body><h1>Synthetic offer</h1>'
                        text += '<dl>' + ''.join('<dt>'+html.escape(k)+'</dt><dd>'+html.escape(str(latest[k]))+'</dd>' for k in ['external_id','amount','terms','revision']) + '</dl></body></html>'
                        return self.send(200, text, 'text/html')
                    return self.send(404, {'error': 'unknown_route'})

            def do_POST(self):
                with owner._lock:
                    owner.requests.append({'method': 'POST', 'path': self.path})
                    if self.path != '/subscriptions':
                        return self.send(405, {'error': 'read_only_provider'})
                    try:
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 4096:
                            raise ValueError('body size')
                        data = json.loads(self.rfile.read(length))
                        callback = data['callback_url']
                        parts = urlsplit(callback)
                        if parts.scheme != 'http' or parts.hostname != '127.0.0.1' or not parts.port or parts.username or parts.password or parts.fragment:
                            raise ValueError('loopback callback required')
                    except (ValueError, TypeError, KeyError):
                        return self.send(400, {'error': 'invalid_callback'})
                    if not owner.webhook_supported:
                        return self.send(409, {'error': 'webhook_unavailable'})
                    owner.subscriptions[:] = [callback]
                    return self.send(200, {'subscribed': True})

            def do_PUT(self):
                with owner._lock:
                    owner.requests.append({'method': self.command, 'path': self.path})
                self.send(405, {'error': 'read_only_provider'})

            do_DELETE = do_PUT
            do_PATCH = do_PUT

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def extend(self, events):
        """Test owner controls fixtures directly, never through a candidate HTTP endpoint."""
        with self._lock:
            self.events.extend(deepcopy(events))

    def push(self, events):
        """Deliver actual HTTP callbacks; returns each observed status and decoded body."""
        with self._lock:
            callbacks = list(self.subscriptions)
        observations = []
        for callback in callbacks:
            request = Request(callback, data=json.dumps({'events': events}).encode(), headers={'Content-Type': 'application/json'}, method='POST')
            try:
                response = urlopen(request, timeout=5)
            except HTTPError as error:
                response = error
            with response:
                observations.append({'status': response.status, 'body': json.loads(response.read())})
        return observations


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=Path, required=True)
    parser.add_argument('--webhooks', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    with OfferService(json.loads(args.events.read_text()), webhook_supported=args.webhooks, port=args.port) as service:
        print(service.url, flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
