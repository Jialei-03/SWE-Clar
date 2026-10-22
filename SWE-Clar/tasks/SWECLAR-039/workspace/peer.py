"""Runnable synthetic device peer; no radio, physical hardware or customer account."""
import argparse
import json
import socketserver
import threading
from pathlib import Path
from wire import receive, transmit


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            request = receive(self.request)
            with self.server.lock:
                op = request.get('op')
                identifier = request.get('device_id')
                packets = []
                if op == 'scan':
                    response = {'ok': True, 'devices': self.server.devices}
                elif op == 'pair':
                    valid = identifier in self.server.codes and self.server.codes[identifier] == request.get('code')
                    if valid:
                        del self.server.codes[identifier]
                        self.server.paired.add(identifier)
                        if self.server.state_path:
                            self.server.state_path.write_text(json.dumps({'paired':sorted(self.server.paired)}))
                    response = {'ok': valid}
                elif op == 'connect':
                    valid = identifier in self.server.paired
                    if valid: self.server.connected = identifier
                    response = {'ok': valid}
                elif op == 'disconnect':
                    self.server.connected = None
                    response = {'ok': True}
                elif op == 'command' and identifier == self.server.connected:
                    command_id = request['command_id']
                    packets = [{'device_id': identifier, 'packet_id': command_id + '-sample',
                                'data': {'value': 12.5, 'unit': 'synthetic', 'running': request['name'] == 'start'}}]
                    response = {'ok': True, 'command_id': command_id, 'result': {'accepted': request['name']}, 'packet_count': len(packets)}
                else:
                    response = {'ok': False}
                transmit(self.request, response)
                for packet in packets: transmit(self.request, packet)
        except (ValueError, OSError, KeyError, TypeError):
            return


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=0); parser.add_argument('--state'); args = parser.parse_args()
    with socketserver.ThreadingTCPServer(('127.0.0.1', args.port), Handler) as server:
        server.daemon_threads = True; server.lock = threading.Lock()
        server.devices = [{'device_id':'SENSOR-A','name':'Synthetic sensor A','services':['capture.v1']},
                          {'device_id':'SENSOR-B','name':'Synthetic sensor B','services':['capture.v1']},
                          {'device_id':'OTHER-C','name':'Other simulator','services':['other.v1']}]
        server.codes = {'SENSOR-A':'DEMO-PAIR-A','SENSOR-B':'DEMO-PAIR-B'}
        server.state_path = Path(args.state) if args.state else None
        saved = json.loads(server.state_path.read_text()) if server.state_path and server.state_path.exists() else {'paired':[]}
        server.paired = set(saved['paired']); server.connected = None
        for identifier in server.paired: server.codes.pop(identifier, None)
        print(json.dumps({'port':server.server_address[1]}), flush=True)
        server.serve_forever()


if __name__ == '__main__': main()
