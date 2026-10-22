"""Synthetic loopback voice-room transport. No accounts or external delivery."""
import argparse
import base64
import io
import json
import math
import struct
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from solution import process_voice_event


def demo_audio():
    out = io.BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b''.join(struct.pack('<h', round(9000 * math.sin(2 * math.pi * 440 * i / 8000))) for i in range(2000)))
    return out.getvalue()


def make_server(port=0):
    state = {'admins': ['admin'], 'rooms': {}}
    deliveries = {}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type='application/json'):
            if content_type == 'application/json':
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path)
            if path.path == '/':
                return self.send(200, Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
            if path.path == '/health':
                return self.send(200, {'ok': True})
            if path.path == '/demo.wav':
                return self.send(200, demo_audio(), 'audio/wav')
            if path.path == '/inbox':
                fields = parse_qs(path.query)
                key = (fields.get('room_id', [''])[0], fields.get('user_id', [''])[0])
                with lock:
                    messages = deliveries.pop(key, [])
                return self.send(200, {'packets': messages})
            self.send(404, {'error': {'code': 'not_found'}})

        def do_POST(self):
            nonlocal state
            if self.path != '/events':
                return self.send(404, {'error': {'code': 'not_found'}})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if size < 1 or size > 2097152:
                    raise ValueError('invalid request size')
                event = json.loads(self.rfile.read(size))
                if not isinstance(event, dict):
                    raise ValueError('event must be an object')
                with lock:
                    output = process_voice_event(state, event)
                    if not isinstance(output, dict):
                        raise ValueError('event processor must return an object')
                    state = output
                    # The application controls eligibility and replay. This transport
                    # delivers the actual accepted bytes to the selected inboxes.
                    result = output.get('result', {})
                    if event.get('type') == 'audio' and 'error' not in output:
                        audio = base64.b64decode(result['audio_base64'], validate=True)
                        packet = {'packet_id': result['packet_id'], 'audio_base64': base64.b64encode(audio).decode()}
                        for user in result['recipients']:
                            deliveries.setdefault((event['room_id'], user), []).append(packet.copy())
                self.send(400 if 'error' in output else 200, output)
            except (ValueError, KeyError, TypeError):
                self.send(400, {'error': {'code': 'invalid_event'}})

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    server = make_server(args.port)
    print(json.dumps({'port': server.server_port}), flush=True)
    server.serve_forever()
