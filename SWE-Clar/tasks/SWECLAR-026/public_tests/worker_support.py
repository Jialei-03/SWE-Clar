"""Benchmark-owned loopback fixture; starts before the candidate application."""
import json
import socketserver
import threading
import uuid


class Worker:
    def __init__(self):
        self.requests = []
        self.receipt = 'fixture-' + uuid.uuid4().hex
        owner = self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for line in self.rfile:
                    try:
                        request = json.loads(line)
                        owner.requests.append(request)
                        response = owner.reply(request)
                        if response is None:
                            return
                        self.wfile.write(response if isinstance(response, bytes) else (json.dumps(response) + '\n').encode())
                        self.wfile.flush()
                    except (ValueError, KeyError, TypeError, OSError):
                        return
        self.server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':0.01}, daemon=True)

    def reply(self, request):
        points = request['points']
        samples = []
        for x in request['positions']:
            y = points[0]['y'] if x <= points[0]['x'] else points[-1]['y']
            for left, right in zip(points, points[1:]):
                if left['x'] <= x <= right['x']:
                    fraction = (x-left['x'])/(right['x']-left['x'])
                    y = (1-fraction)*left['y'] + fraction*right['y']
                    break
            samples.append({'x':x,'y':y})
        return {'sequence':request['sequence'],'samples':samples,'receipt':self.receipt}

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
