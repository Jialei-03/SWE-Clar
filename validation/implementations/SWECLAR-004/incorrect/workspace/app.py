"""Offline HTTP application. All accounts and receipts are synthetic fixtures."""
import argparse
import hmac
import json
import math
import re
import secrets
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import policies
from storage import connect, initialize, password_hash, public_user


class Problem(Exception):
    def __init__(self, status, code):
        self.status = status
        self.code = code
        super().__init__(code)


def require(condition, code='invalid', status=400):
    if not condition:
        raise Problem(status, code)


def text(value, limit):
    require(isinstance(value, str))
    trimmed = value.strip()
    require(1 <= len(trimmed) <= limit)
    return trimmed


def number(value, lo, hi):
    # bool is an int subclass, but is not a coordinate/radius number in the
    # public schema.  Guard very large JSON integers before math.isfinite.
    require(type(value) in (int, float))
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        finite = False
    require(finite and lo <= value <= hi)
    return value


def fields(body, required):
    require(isinstance(body, dict) and set(body) == set(required))


def strict_object(pairs):
    """Reject duplicate JSON object keys rather than silently choosing one."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def reject_json_constant(_value):
    raise ValueError('non-finite JSON number')


class Handler(BaseHTTPRequestHandler):
    # Only these files are public.  In particular, do not turn the web
    # directory into a general-purpose file server.
    STATIC = {
        '/': ('index.html', 'text/html'),
        '/ui.js': ('ui.js', 'text/javascript'),
        '/style.css': ('style.css', 'text/css'),
    }
    ENDPOINTS = {
        ('POST', '/api/login'),
        ('POST', '/api/logout'),
        ('GET', '/api/me'),
        ('GET', '/api/people'),
        ('PUT', '/api/profile'),
        ('GET', '/api/matches'),
        ('POST', '/api/connection'),
        ('POST', '/api/block'),
        ('POST', '/api/message'),
        ('POST', '/api/group'),
        ('POST', '/api/invite'),
        ('POST', '/api/post'),
        ('POST', '/api/like'),
        ('POST', '/api/subscribe'),
        ('GET', '/api/dashboard'),
        ('GET', '/health'),
    }
    NO_QUERY = {
        '/health',
        '/api/login',
        '/api/logout',
        '/api/me',
        '/api/people',
        '/api/profile',
        '/api/connection',
        '/api/block',
        '/api/message',
        '/api/group',
        '/api/invite',
        '/api/post',
        '/api/like',
        '/api/subscribe',
        '/api/dashboard',
    }

    def log_message(self, *_):
        # The service is intended for local test use and must not log bearer
        # headers or user-entered content.
        pass

    def send(self, status, data, kind='application/json'):
        if kind == 'application/json':
            raw = json.dumps(
                data, ensure_ascii=False, allow_nan=False, separators=(',', ':')
            ).encode('utf-8')
        else:
            raw = data
        self.send_response(status)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PUT(self):
        self.handle_request()

    # Return the same JSON-shaped error for accidental unsupported methods
    # instead of BaseHTTPRequestHandler's HTML error page.
    def do_DELETE(self):
        self.handle_request()

    def do_PATCH(self):
        self.handle_request()

    def do_OPTIONS(self):
        self.handle_request()

    def handle_request(self):
        try:
            route = urlparse(self.path)
            static = self.STATIC.get(route.path) if self.command == 'GET' else None
            if static is not None:
                filename, kind = static
                self.send(200, (Path(__file__).parent / 'web' / filename).read_bytes(), kind)
                return

            if (self.command, route.path) not in self.ENDPOINTS:
                raise Problem(404, 'not_found')
            if route.path in self.NO_QUERY:
                require(not route.query)

            body = {}
            if self.command in ('POST', 'PUT'):
                body = self.read_json_body()

            db = connect(self.server.db_path)
            try:
                result = self.dispatch(db, route, body)
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
            self.send(200, result)
        except Problem as problem:
            self.send(problem.status, {'error': {'code': problem.code}})
        except (ValueError, UnicodeError, OverflowError, TypeError, json.JSONDecodeError):
            self.send(400, {'error': {'code': 'invalid'}})

    def read_json_body(self):
        raw_length = self.headers.get('Content-Length')
        require(raw_length is not None)
        try:
            length = int(raw_length)
        except (TypeError, ValueError, OverflowError):
            raise Problem(400, 'invalid')
        require(0 < length <= 16384)
        raw = self.rfile.read(length)
        require(len(raw) == length)
        try:
            decoded = raw.decode('utf-8')
            value = json.loads(
                decoded,
                object_pairs_hook=strict_object,
                parse_constant=reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            raise Problem(400, 'invalid')
        require(isinstance(value, dict))
        return value

    def user(self, db):
        authorization = self.headers.get('Authorization', '')
        require(
            isinstance(authorization, str)
            and authorization.startswith('Bearer ')
            and bool(authorization[7:])
            and not any(ch.isspace() for ch in authorization[7:]),
            'unauthorized',
            401,
        )
        row = db.execute(
            '''SELECT users.* FROM sessions
               JOIN users ON users.id=sessions.user_id
               WHERE sessions.token=?''',
            (authorization[7:],),
        ).fetchone()
        require(row is not None, 'unauthorized', 401)
        return row

    def target(self, db, body):
        require(isinstance(body.get('target'), str))
        row = db.execute(
            'SELECT * FROM users WHERE id=?', (body['target'],)
        ).fetchone()
        require(row is not None, 'not_found', 404)
        return row['id']

    def group(self, db, ident):
        require(isinstance(ident, str))
        row = db.execute('SELECT * FROM groups WHERE id=?', (ident,)).fetchone()
        require(row is not None, 'not_found', 404)
        return row

    def begin_write(self, db):
        # All authenticated mutations inspect policy state and write it as one
        # serialized operation.  This also makes concurrent receipt replay and
        # connection creation deterministic.
        db.execute('BEGIN IMMEDIATE')

    def dispatch(self, db, route, body):
        path = route.path
        method = self.command

        if method == 'GET' and path == '/health':
            return {'ok': True}

        if method == 'POST' and path == '/api/login':
            fields(body, {'id', 'password'})
            require(
                isinstance(body['id'], str) and isinstance(body['password'], str)
            )
            row = db.execute(
                'SELECT * FROM users WHERE id=?', (body['id'],)
            ).fetchone()
            valid = row is not None and hmac.compare_digest(
                row['password_hash'], password_hash(body['password'])
            )
            require(valid, 'unauthorized', 401)
            self.begin_write(db)
            token = secrets.token_urlsafe(32)
            # The token is overwhelmingly unlikely to collide, but retaining
            # the loop makes distinct-token behavior explicit even if a random
            # source is replaced in a test.
            while True:
                try:
                    db.execute(
                        'INSERT INTO sessions(token,user_id) VALUES(?,?)',
                        (token, row['id']),
                    )
                    break
                except Exception as error:
                    if 'UNIQUE' not in str(error).upper():
                        raise
                    token = secrets.token_urlsafe(32)
            current = db.execute(
                'SELECT * FROM users WHERE id=?', (row['id'],)
            ).fetchone()
            return {'token': token, 'user': public_user(current)}

        # Every route after login is protected.  The actor is obtained only
        # from this server-side session lookup.
        user = self.user(db)
        actor = user['id']

        if method in ('POST', 'PUT'):
            self.begin_write(db)
            # Revalidate after acquiring the writer lock so a request racing
            # with logout cannot mutate state using a token that was already
            # revoked by the time its write began.
            user = self.user(db)
            actor = user['id']

        if method == 'POST' and path == '/api/logout':
            fields(body, set())
            authorization = self.headers['Authorization']
            db.execute(
                'DELETE FROM sessions WHERE token=?', (authorization[7:],)
            )
            return {'ok': True}

        if method == 'GET' and path == '/api/me':
            return {'user': public_user(user)}

        if method == 'GET' and path == '/api/people':
            people = [
                dict(row)
                for row in db.execute('SELECT id,display,role FROM users')
            ]
            people.sort(key=lambda person: person['id'])
            return {'people': people}

        if method == 'PUT' and path == '/api/profile':
            fields(body, {'interests', 'x', 'y'})
            interests = body['interests']
            require(
                isinstance(interests, list)
                and len(interests) <= 10
                and len(set(interests)) == len(interests)
                and all(
                    isinstance(item, str)
                    and re.fullmatch(r'[a-z][a-z0-9_-]{0,23}', item)
                    for item in interests
                )
            )
            x = number(body['x'], -1000, 1000)
            y = number(body['y'], -1000, 1000)
            db.execute(
                'UPDATE users SET interests=?,x=?,y=? WHERE id=?',
                (json.dumps(interests, ensure_ascii=False), x, y, actor),
            )
            return {
                'user': public_user(
                    db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone()
                )
            }

        if method == 'GET' and path == '/api/matches':
            query = parse_qs(route.query, keep_blank_values=True)
            require(
                set(query) <= {'radius', 'role'}
                and all(len(values) == 1 for values in query.values())
            )
            raw_radius = query.get('radius', ['100'])[0]
            try:
                radius = float(raw_radius)
            except (TypeError, ValueError, OverflowError):
                raise Problem(400, 'invalid')
            require(math.isfinite(radius) and 0 <= radius <= 3000)
            role = query.get('role', ['all'])[0]
            require(role in {'all', 'user', 'business'})
            return {'matches': policies.matches(db, actor, radius, role)}

        if method == 'POST' and path == '/api/connection':
            fields(body, {'target', 'decision'})
            target = self.target(db, body)
            decision = body['decision']
            require(target != actor and decision in {'request', 'accept'})
            left, right = sorted((actor, target))
            existing = db.execute(
                'SELECT * FROM connections WHERE a=? AND b=?',
                (left, right),
            ).fetchone()
            require(
                policies.connection_allowed(
                    db, actor, target, decision, existing
                ),
                'denied',
                403,
            )
            if existing is None:
                db.execute(
                    '''INSERT INTO connections(a,b,requester,accepted)
                       VALUES(?,?,?,0)''',
                    (left, right, actor),
                )
            elif decision == 'accept':
                # The policy has already established that actor is the
                # original recipient.  A repeated accept is idempotent.
                db.execute(
                    'UPDATE connections SET accepted=1 WHERE a=? AND b=?',
                    (left, right),
                )
            current = db.execute(
                'SELECT accepted FROM connections WHERE a=? AND b=?',
                (left, right),
            ).fetchone()
            return {'accepted': bool(current['accepted'])}

        if method == 'POST' and path == '/api/block':
            fields(body, {'target', 'blocked'})
            target = self.target(db, body)
            require(target != actor and type(body['blocked']) is bool)
            if body['blocked']:
                db.execute(
                    'INSERT OR IGNORE INTO blocks(actor,target) VALUES(?,?)',
                    (actor, target),
                )
            else:
                db.execute(
                    'DELETE FROM blocks WHERE actor=? AND target=?',
                    (actor, target),
                )
            return {'ok': True}

        if method == 'POST' and path == '/api/message':
            fields(body, {'target', 'content'})
            target = self.target(db, body)
            content = text(body['content'], 2000)
            require(target != actor)
            require(
                policies.message_allowed(db, actor, target),
                'denied',
                403,
            )
            ident = uuid.uuid4().hex
            db.execute(
                '''INSERT INTO messages(id,sender,recipient,content)
                   VALUES(?,?,?,?)''',
                (ident, actor, target, content),
            )
            return {'id': ident}

        if method == 'POST' and path == '/api/group':
            fields(body, {'name'})
            name = text(body['name'], 80)
            ident = uuid.uuid4().hex
            db.execute(
                'INSERT INTO groups(id,owner,name) VALUES(?,?,?)',
                (ident, actor, name),
            )
            db.execute(
                'INSERT INTO members(group_id,user_id) VALUES(?,?)',
                (ident, actor),
            )
            return {'id': ident}

        if method == 'POST' and path == '/api/invite':
            fields(body, {'group_id', 'target'})
            group = self.group(db, body['group_id'])
            target = self.target(db, body)
            require(
                policies.invite_allowed(db, actor, target, group),
                'denied',
                403,
            )
            db.execute(
                'INSERT OR IGNORE INTO members(group_id,user_id) VALUES(?,?)',
                (group['id'], target),
            )
            return {'ok': True}

        if method == 'POST' and path == '/api/post':
            fields(body, {'group_id', 'content', 'featured'})
            group = self.group(db, body['group_id'])
            content = text(body['content'], 2000)
            require(type(body['featured']) is bool)
            require(
                policies.post_allowed(db, actor, group),
                'denied',
                403,
            )
            # Fetch the current row rather than trusting any client-supplied
            # plan (there is no plan field in this request at all).
            current_user = db.execute(
                'SELECT * FROM users WHERE id=?', (actor,)
            ).fetchone()
            require(
                not body['featured'] or policies.featured_allowed(current_user),
                'denied',
                403,
            )
            ident = uuid.uuid4().hex
            db.execute(
                '''INSERT INTO posts(id,group_id,author,content,featured)
                   VALUES(?,?,?,?,?)''',
                (ident, group['id'], actor, content, int(body['featured'])),
            )
            return {'id': ident}

        if method == 'POST' and path == '/api/like':
            fields(body, {'post_id'})
            require(isinstance(body['post_id'], str))
            post = db.execute(
                'SELECT * FROM posts WHERE id=?', (body['post_id'],)
            ).fetchone()
            require(post is not None, 'not_found', 404)
            group = self.group(db, post['group_id'])
            require(
                policies.like_allowed(db, actor, post, group),
                'denied',
                403,
            )
            policies.store_like(db, actor, post['id'])
            count = db.execute(
                'SELECT COUNT(*) AS count FROM likes WHERE post_id=?',
                (post['id'],),
            ).fetchone()['count']
            return {'likes': int(count)}

        if method == 'POST' and path == '/api/subscribe':
            fields(body, {'receipt_id'})
            require(isinstance(body['receipt_id'], str))
            receipt = next(
                (
                    item
                    for item in self.server.fixtures.get('receipts', [])
                    if item.get('id') == body['receipt_id']
                ),
                None,
            )
            require(
                receipt is not None and policies.membership_allowed(user, receipt),
                'denied',
                403,
            )
            # begin_write above serializes the catalog lookup, consumption
            # check and plan replacement with identical concurrent requests.
            applied = policies.apply_membership(db, user, receipt)
            require(applied, 'denied', 403)
            current_plan = db.execute(
                'SELECT plan FROM users WHERE id=?', (actor,)
            ).fetchone()['plan']
            return {'plan': current_plan}

        if method == 'GET' and path == '/api/dashboard':
            connections = []
            for connection in db.execute(
                '''SELECT * FROM connections
                   WHERE a=? OR b=? ORDER BY rowid''',
                (actor, actor),
            ):
                target = (
                    connection['b']
                    if connection['a'] == actor
                    else connection['a']
                )
                if not policies.blocked_either(db, actor, target):
                    connections.append(
                        {
                            'target': target,
                            'accepted': bool(connection['accepted']),
                            'incoming': connection['requester'] != actor,
                        }
                    )

            groups = []
            for group in db.execute(
                '''SELECT groups.id,groups.owner,groups.name
                   FROM groups JOIN members ON groups.id=members.group_id
                   WHERE members.user_id=? ORDER BY groups.rowid''',
                (actor,),
            ):
                if policies.unblocked_pair(db, actor, group['owner']):
                    groups.append(dict(group))
            group_ids = {group['id'] for group in groups}

            posts = []
            for post in db.execute('SELECT * FROM posts ORDER BY rowid'):
                if post['group_id'] not in group_ids:
                    continue
                group = db.execute(
                    'SELECT * FROM groups WHERE id=?', (post['group_id'],)
                ).fetchone()
                if group is None or not policies.post_visible(
                    db, actor, post, group
                ):
                    continue
                item = {
                    'id': post['id'],
                    'group_id': post['group_id'],
                    'author': post['author'],
                    'content': post['content'],
                    'featured': bool(post['featured']),
                    'likes': int(
                        db.execute(
                            'SELECT COUNT(*) AS count FROM likes WHERE post_id=?',
                            (post['id'],),
                        ).fetchone()['count']
                    ),
                }
                posts.append(item)

            messages = []
            for message in db.execute(
                '''SELECT id,sender,recipient,content FROM messages
                   WHERE sender=? OR recipient=? ORDER BY rowid''',
                (actor, actor),
            ):
                if not policies.blocked_either(
                    db, message['sender'], message['recipient']
                ):
                    messages.append(dict(message))

            blocked_list = sorted(
                row['target']
                for row in db.execute(
                    'SELECT target FROM blocks WHERE actor=?',
                    (actor,),
                )
            )
            return {
                'connections': connections,
                'groups': groups,
                'posts': posts,
                'messages': messages,
                'blocked': blocked_list,
            }

        # ENDPOINTS prevents this for normal requests, but keep the dispatch
        # boundary explicit if it is ever called directly.
        raise Problem(404, 'not_found')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='network.sqlite')
    parser.add_argument('--fixtures', default='fixtures/demo.json')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    fixtures = json.loads(Path(args.fixtures).read_text(encoding='utf-8'))
    initialize(args.db, fixtures)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.db_path = args.db
    server.fixtures = fixtures
    print(server.server_port, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
