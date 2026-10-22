"""Independent authoritative grid arena; no original game code or assets."""
import copy
import json
from pathlib import Path
import re
import secrets
import threading
import time


class Conflict(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def reject(status, code):
    raise Conflict(status, code)


class Arena:
    def __init__(self, world, clock_file):
        self.rooms = {room['id']: copy.deepcopy(room) for room in world['rooms']}
        self.clock_file = Path(clock_file)
        self.players = {}
        self.sessions = {}
        self.commands = {}
        self.seq = 0
        self.lock = threading.RLock()

    def now(self):
        clock = json.loads(self.clock_file.read_text())
        if clock.get('mode') == 'realtime':
            return time.time_ns() // 1_000_000
        value = clock['now_ms']
        if type(value) is not int or value < 0:
            raise ValueError('Invalid benchmark clock')
        return value

    def catalog(self):
        return {'rooms': [{k: room[k] for k in ('id', 'label', 'cols', 'rows')} for room in self.rooms.values()]}

    def actor(self, token):
        pid = self.sessions.get(token)
        if pid not in self.players:
            reject(401, 'unauthenticated')
        return self.players[pid]

    def free_spawn(self, room_id):
        occupied = {(p['x'], p['y']) for p in self.players.values() if p['room_id'] == room_id and p['alive']}
        for x, y in self.rooms[room_id]['spawn_points']:
            if (x, y) not in occupied:
                return x, y
        reject(409, 'conflict')

    def spawn(self, player, now, position):
        player.update(x=position[0], y=position[1], hp=3, alive=True,
                      generation=player.get('generation', 0) + 1,
                      spawn_ms=now, protected_until_ms=now)

    def snapshot(self, actor, now):
        self.seq += 1
        room_id = actor['room_id']
        room = self.rooms[room_id]
        return {'room': {k: copy.deepcopy(room[k]) for k in ('id', 'label', 'cols', 'rows', 'walls')},
                'seq': self.seq, 'server_now_ms': now,
                'players': [{k: v for k, v in p.items() if k != 'room_id'}
                            for p in self.players.values() if p['room_id'] == room_id]}

    def join(self, body):
        room_id, label = body.get('room_id'), body.get('label')
        if not isinstance(room_id, str) or not isinstance(label, str) or not 1 <= len(label.strip()) <= 40:
            reject(400, 'invalid_request')
        with self.lock:
            if room_id not in self.rooms:
                reject(404, 'not_found')
            position = self.free_spawn(room_id)
            now = self.now()
            player = {'id': 'player_' + secrets.token_hex(12), 'room_id': room_id, 'label': label.strip()}
            self.spawn(player, now, position)
            token = secrets.token_hex(32)
            self.players[player['id']] = player
            self.sessions[token] = player['id']
            return {'token': token, 'player_id': player['id'], 'state': self.snapshot(player, now)}

    def state(self, token):
        with self.lock:
            actor = self.actor(token)
            return {'state': self.snapshot(actor, self.now())}

    def leave(self, token):
        with self.lock:
            actor = self.actor(token)
            del self.sessions[token]
            del self.players[actor['id']]
            self.commands = {k: v for k, v in self.commands.items() if k[0] != actor['id']}
            return {'ok': True}

    @staticmethod
    def protected(player, now):
        # Spawn-protection collision policy is unfinished.
        return False

    def move_player(self, actor, direction, now):
        if not actor['alive']:
            reject(409, 'conflict')
        dx, dy = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}[direction]
        x, y = actor['x'] + dx, actor['y'] + dy
        room = self.rooms[actor['room_id']]
        if not 0 <= x < room['cols'] or not 0 <= y < room['rows'] or [x, y] in room['walls']:
            return
        collision = any(p['id'] != actor['id'] and p['room_id'] == actor['room_id'] and p['alive']
                        and (p['x'], p['y']) == (x, y)
                        and not self.protected(actor, now) and not self.protected(p, now)
                        for p in self.players.values())
        if collision:
            actor['hp'] -= 1
            actor['alive'] = actor['hp'] > 0
        else:
            actor.update(x=x, y=y)

    def command(self, token, operation, body):
        with self.lock:
            actor = self.actor(token)
            generation, command_id = body.get('generation'), body.get('command_id')
            direction = body.get('direction')
            if (type(generation) is not int or generation < 1 or not isinstance(command_id, str)
                    or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', command_id) is None
                    or (operation == 'move' and direction not in ('left', 'right', 'up', 'down'))):
                reject(400, 'invalid_request')
            # Command replay is unfinished.
            now = self.now()
            if generation != actor['generation']:
                reject(409, 'conflict')
            if operation == 'move':
                self.move_player(actor, direction, now)
            elif operation == 'respawn':
                reject(501, 'not_implemented')
            else:
                reject(404, 'not_found')
            return {'state': self.snapshot(actor, now)}
