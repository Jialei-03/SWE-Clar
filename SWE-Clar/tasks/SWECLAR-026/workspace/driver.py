"""Runnable local reference driver; no physical device or external service."""
import argparse
import json
import socketserver


def interpolate(points, x):
    if x <= points[0]['x']:
        return points[0]['y']
    if x >= points[-1]['x']:
        return points[-1]['y']
    for a, b in zip(points, points[1:]):
        if a['x'] <= x <= b['x']:
            return a['y'] + (x - a['x']) * (b['y'] - a['y']) / (b['x'] - a['x'])
    raise ValueError('Unordered curve')


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            try:
                request = json.loads(line)
                samples = [{'x': x, 'y': interpolate(request['points'], x)} for x in request['positions']]
                response = {'sequence': request['sequence'], 'samples': samples, 'receipt': 'local-driver'}
                self.wfile.write((json.dumps(response) + '\n').encode())
                self.wfile.flush()
            except (ValueError, KeyError, TypeError):
                return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    with socketserver.ThreadingTCPServer(('127.0.0.1', args.port), Handler) as server:
        server.daemon_threads = True
        print(json.dumps({'port': server.server_address[1]}), flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
