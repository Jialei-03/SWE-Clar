"""Serve the independent browser component and a synthetic linear programme."""
import http.server
import io
import json
import math
import os
import re
import struct
import time
import wave
from pathlib import Path

EPOCH = time.monotonic()
stream = io.BytesIO()
with wave.open(stream, 'wb') as output:
    output.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
    output.writeframes(b''.join(
        struct.pack('<h', int(7000 * math.sin(2 * math.pi * 330 * i / 8000)))
        for i in range(8000 * 90)
    ))
AUDIO = stream.getvalue()


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/'):
            page = self.path.split('/')[-1]
            if page == 'live':
                value = {'offset': (time.monotonic() - EPOCH) % 70}
            elif page in ('schedule', 'recent'):
                value = [{
                    'id': page + '-one',
                    'title': page.title() + ' Programme',
                    'artist': 'Synthetic Ensemble',
                    'album': 'Evening Collection',
                    'live': page == 'schedule',
                    'url': '/tone.wav',
                }]
            else:
                self.send_error(404)
                return
            data = json.dumps(value).encode()
            kind = 'application/json'
        elif self.path == '/tone.wav':
            data = AUDIO
            kind = 'audio/wav'
        else:
            return super().do_GET()

        status = 200
        total = len(data)
        start, end = 0, total - 1
        if kind == 'audio/wav' and self.headers.get('Range'):
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', self.headers['Range'])
            if not match:
                self.send_error(416)
                return
            start = int(match[1])
            end = min(int(match[2]) if match[2] else total - 1, total - 1)
            if start > end:
                self.send_error(416)
                return
            status = 206
            data = data[start:end + 1]

        self.send_response(status)
        if kind == 'audio/wav':
            self.send_header('Accept-Ranges', 'bytes')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{total}')
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', len(data))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    os.chdir(Path(__file__).parent)
    address = ('127.0.0.1', int(os.environ.get('PORT', '8765')))
    http.server.ThreadingHTTPServer(address, Handler).serve_forever()
