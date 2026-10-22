"""Protected local provider fixture; evaluates transport, not real model quality."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import threading
import time
from PIL import Image, ImageStat


class ProviderServer(ThreadingHTTPServer):
    def __init__(self, address, state):
        super().__init__(address, Handler)
        self.state = Path(state)
        self.log_lock = threading.Lock()

    def settings(self):
        return json.loads((self.state / 'config.json').read_text())

    def record(self, value):
        with self.log_lock:
            with (self.state / 'requests.jsonl').open('a') as stream:
                stream.write(json.dumps(value) + '\n')


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value):
        body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status);self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)));self.end_headers();self.wfile.write(body)

    def do_GET(self):
        if self.path == '/health':
            return self.reply(200, {'ok': True})
        self.reply(404, {'error': 'not_found'})

    def do_POST(self):
        settings = self.server.settings()
        authorized = self.headers.get('Authorization') == 'Bearer ' + settings['token']
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 1 <= size <= 67108864:
                raise ValueError('Invalid request length')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError('Expected object')
        except (ValueError, UnicodeDecodeError):
            self.server.record({'route': self.path, 'authorized': authorized, 'invalid_body': True})
            return self.reply(400, {'error': 'invalid_request'})
        self.server.record({'route': self.path, 'authorized': authorized, 'payload': payload})
        if not authorized:
            return self.reply(401, {'error': 'unauthorized'})
        if self.path not in {'/coach', '/photo-scores'}:
            return self.reply(404, {'error': 'not_found'})
        if settings.get('delay_ms', 0):
            time.sleep(min(settings['delay_ms'], 5000) / 1000)
        fault = settings.get('faults', {}).get(self.path)
        if fault == 'http_error':
            return self.reply(503, {'error': 'temporary_unavailable'})
        if fault == 'invalid_json':
            return self.reply(200, b'{')
        if self.path in settings.get('responses', {}):
            return self.reply(200, settings['responses'][self.path])
        try:
            if self.path == '/coach':
                if set(payload) != {'system_prompt', 'profile', 'messages', 'question'}:
                    raise ValueError('Unexpected coach fields')
                if not isinstance(payload['question'], str) or not isinstance(payload['system_prompt'], str):
                    raise ValueError('Invalid text input')
                profile = payload['profile']
                if set(profile) != {'tone', 'goal'} or not all(isinstance(value, str) for value in profile.values()):
                    raise ValueError('Invalid preferences')
                if not isinstance(payload['messages'], list) or not all(set(row) == {'sender', 'text'} and row['sender'] in {'me', 'peer'} and isinstance(row['text'], str) for row in payload['messages']):
                    raise ValueError('Invalid messages')
                response = {'advice': 'Synthetic suggestion (' + profile['tone'] + '): consider ' + payload['question']}
            else:
                if set(payload) != {'preferences', 'images'} or set(payload['preferences']) != {'tone', 'goal'} or not isinstance(payload['images'], list):
                    raise ValueError('Invalid image request')
                scores = []
                for row in payload['images']:
                    if set(row) != {'asset_id', 'mime_type', 'image_base64'} or row['mime_type'] != 'image/png':
                        raise ValueError('Invalid image metadata')
                    raw = base64.b64decode(row['image_base64'], validate=True)
                    with Image.open(BytesIO(raw)) as image:
                        if image.format != 'PNG' or not 1 <= image.width <= 1600 or not 1 <= image.height <= 1600 or image.width * image.height > 2000000:
                            raise ValueError('Invalid PNG')
                        image.load();score = round(ImageStat.Stat(image.convert('L')).mean[0] / 255 * 100, 6)
                    scores.append({'asset_id': row['asset_id'], 'score': score, 'reasons': ['Synthetic luminance-based fixture result']})
                response = {'scores': scores}
        except (ValueError, TypeError, KeyError, OSError):
            return self.reply(400, {'error': 'invalid_request'})
        self.reply(200, response)

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8081)
    parser.add_argument('--state', required=True)
    args = parser.parse_args()
    if os.getuid() != 2000:
        raise SystemExit('Provider must run as its separate unprivileged identity')
    caps = Path('/proc/self/status').read_text()
    assert int(next(line for line in caps.splitlines() if line.startswith('CapEff:')).split()[1], 16) == 0
    server = ProviderServer(('127.0.0.1', args.port), args.state)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
