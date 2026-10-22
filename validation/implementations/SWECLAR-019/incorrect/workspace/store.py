"""Durable authenticated route-workspace records backed by SQLite."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import math
from pathlib import Path
import secrets
import sqlite3
import threading
from urllib.parse import quote

from media import sanitize


class Failure(Exception):
    def __init__(self, status, code):
        self.status = status
        self.code = code
        super().__init__(code)


def invalid():
    raise Failure(400, 'invalid_request')


def conflict():
    raise Failure(409, 'conflict')


def not_found():
    raise Failure(404, 'not_found')


def text(value, maximum):
    """Validate and return a trimmed user-facing string."""
    if not isinstance(value, str):
        invalid()
    value = value.strip()
    if not 1 <= len(value) <= maximum:
        invalid()
    return value


def identifier(value):
    if not isinstance(value, str) or not value:
        invalid()
    return value


def revision(value):
    # bool is an int subclass, but is not a revision in this contract.
    if type(value) is not int or value < 0:
        invalid()
    return value


def coordinate(value, limit):
    # JSON booleans must not be accepted as coordinates.
    if type(value) not in (int, float):
        invalid()
    if not -limit <= value <= limit or not math.isfinite(value):
        invalid()
    return value


def unique_ids(value, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        invalid()
    for item in value:
        identifier(item)
    if len(set(value)) != len(value):
        invalid()
    return value


def fold(value):
    """Fold only ASCII A-Z, leaving every other code point unchanged."""
    return value.translate(str.maketrans(
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))


class Store:
    def __init__(self, database, fixture):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        # Sessions are deliberately process-memory-only.  A server restart logs
        # every browser session out without affecting domain data.
        self.sessions = {}

        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS initialized (version INTEGER)')
            db.execute(
                'CREATE TABLE IF NOT EXISTS users ('
                'id TEXT PRIMARY KEY, username TEXT UNIQUE, salt TEXT, password TEXT,'
                'name TEXT, photo_id TEXT, touring_status TEXT)')
            db.execute(
                'CREATE TABLE IF NOT EXISTS assets ('
                'id TEXT PRIMARY KEY, owner_id TEXT, width INTEGER, height INTEGER, png BLOB)')
            db.execute(
                'CREATE TABLE IF NOT EXISTS waypoints ('
                'id TEXT PRIMARY KEY, owner_id TEXT, name TEXT, lat REAL, lon REAL,'
                'photo_ids TEXT, revision INTEGER)')
            db.execute(
                'CREATE TABLE IF NOT EXISTS routes ('
                'id TEXT PRIMARY KEY, owner_id TEXT, title TEXT, waypoint_ids TEXT)')
            db.execute(
                'CREATE TABLE IF NOT EXISTS pins ('
                'user_id TEXT, route_id TEXT, PRIMARY KEY(user_id, route_id))')
            db.execute(
                'CREATE TABLE IF NOT EXISTS comments ('
                'id TEXT PRIMARY KEY, waypoint_id TEXT, author_id TEXT, text TEXT,'
                'request_id TEXT, UNIQUE(author_id, request_id))')
            if db.execute('SELECT version FROM initialized').fetchone() is None:
                fixture_users = json.loads(Path(fixture).read_text())['users']
                for user in fixture_users:
                    salt = secrets.token_hex(16)
                    db.execute(
                        'INSERT INTO users VALUES (?,?,?,?,?,?,?)',
                        (user['id'], user['username'], salt,
                         self.password(user['password'], salt), '', None, 'planned'))
                db.execute('INSERT INTO initialized VALUES (1)')

    @contextmanager
    def transaction(self):
        # The process lock makes the read/modify/write operations deterministic
        # for ThreadingHTTPServer, while BEGIN IMMEDIATE also gives SQLite an
        # atomic durable transaction boundary.
        with self.lock:
            db = sqlite3.connect(self.database, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                db.execute('BEGIN IMMEDIATE')
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    @staticmethod
    def password(value, salt):
        return hashlib.pbkdf2_hmac(
            'sha256', value.encode('utf-8'), bytes.fromhex(salt), 120000).hex()

    @staticmethod
    def _name_present(row):
        return isinstance(row['name'], str) and bool(row['name'].strip())

    def user_value(self, db, row):
        # Checking the asset row as well as the non-null foreign reference keeps
        # profile_required truthful even if a database is inspected or repaired
        # outside the public API.
        photo = row['photo_id']
        owned_photo = False
        if isinstance(photo, str) and photo:
            owned_photo = db.execute(
                'SELECT 1 FROM assets WHERE id=? AND owner_id=?',
                (photo, row['id'])).fetchone() is not None
        return {
            'id': row['id'],
            'username': row['username'],
            'name': row['name'],
            'photo_id': photo,
            'touring_status': row['touring_status'],
            'profile_required': not (self._name_present(row) and owned_photo),
        }

    @staticmethod
    def waypoint_value(row):
        return {
            'id': row['id'],
            'owner_id': row['owner_id'],
            'name': row['name'],
            'lat': row['lat'],
            'lon': row['lon'],
            'photo_ids': json.loads(row['photo_ids']),
            'revision': row['revision'],
        }

    @staticmethod
    def asset_value(row):
        return {
            'id': row['id'],
            'width': row['width'],
            'height': row['height'],
            'url': '/api/assets/' + quote(row['id'], safe=''),
        }

    def user_row(self, db, actor):
        row = db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone()
        if row is None:
            raise Failure(401, 'unauthenticated')
        return row

    def complete(self, db, actor):
        row = self.user_row(db, actor)
        if self.user_value(db, row)['profile_required']:
            raise Failure(403, 'profile_required')
        return row

    @staticmethod
    def waypoint_row(db, key):
        row = db.execute('SELECT * FROM waypoints WHERE id=?', (key,)).fetchone()
        if row is None:
            not_found()
        return row

    @staticmethod
    def route_row(db, key):
        row = db.execute('SELECT * FROM routes WHERE id=?', (key,)).fetchone()
        if row is None:
            not_found()
        return row

    @staticmethod
    def owned_asset(db, actor, key):
        row = db.execute(
            'SELECT * FROM assets WHERE id=? AND owner_id=?', (key, actor)).fetchone()
        if row is None:
            not_found()
        return row

    @staticmethod
    def route_value(db, row, actor):
        pinned = db.execute(
            'SELECT 1 FROM pins WHERE user_id=? AND route_id=?',
            (actor, row['id'])).fetchone() is not None
        return {
            'id': row['id'],
            'owner_id': row['owner_id'],
            'title': row['title'],
            'waypoint_ids': json.loads(row['waypoint_ids']),
            'pinned': pinned,
        }

    def comment_value(self, db, row):
        author = self.user_row(db, row['author_id'])
        return {
            'id': row['id'],
            'waypoint_id': row['waypoint_id'],
            'author': {
                'id': author['id'],
                'name': author['name'],
                'photo_id': author['photo_id'],
            },
            'text': row['text'],
        }

    def login(self, body):
        if not isinstance(body.get('username'), str) or not isinstance(body.get('password'), str):
            invalid()
        with self.transaction() as db:
            row = db.execute(
                'SELECT * FROM users WHERE username=?', (body['username'],)).fetchone()
            if row is None or not hmac.compare_digest(
                    self.password(body['password'], row['salt']), row['password']):
                raise Failure(401, 'unauthenticated')
            # token_urlsafe(32) is generated from at least 32 random bytes.
            token = secrets.token_urlsafe(32)
            self.sessions[token] = row['id']
            return {'token': token, 'user': self.user_value(db, row)}

    def actor(self, authorization):
        token = authorization[7:] if authorization.startswith('Bearer ') else ''
        with self.lock:
            actor = self.sessions.get(token)
        if actor is None:
            raise Failure(401, 'unauthenticated')
        return actor

    def logout(self, authorization):
        token = authorization[7:] if authorization.startswith('Bearer ') else ''
        with self.lock:
            if token not in self.sessions:
                raise Failure(401, 'unauthenticated')
            del self.sessions[token]
        return {'ok': True}

    def me(self, actor):
        with self.transaction() as db:
            return {'user': self.user_value(db, self.user_row(db, actor))}

    def assets(self, actor):
        with self.transaction() as db:
            return {
                'assets': [
                    self.asset_value(row)
                    for row in db.execute(
                        'SELECT * FROM assets WHERE owner_id=? ORDER BY rowid', (actor,))
                ]
            }

    def upload(self, actor, body):
        try:
            png, width, height = sanitize(body.get('png_base64'))
        except Exception:
            # Pillow also raises a DecompressionBombError for some malformed
            # or intentionally enormous PNG headers; every decode failure is
            # an invalid request and must not reach the HTTP thread.
            invalid()
        with self.transaction() as db:
            # A generated ID is the only ID that can be inserted; caller input
            # cannot overwrite an existing asset.
            key = secrets.token_urlsafe(18)
            db.execute(
                'INSERT INTO assets VALUES (?,?,?,?,?)',
                (key, actor, width, height, png))
            return {'asset': self.asset_value(self.owned_asset(db, actor, key))}

    def asset(self, actor, key):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM assets WHERE id=?', (key,)).fetchone()
            if row is None:
                not_found()
            visible = row['owner_id'] == actor
            if not visible:
                visible = db.execute(
                    'SELECT 1 FROM users WHERE photo_id=?', (key,)).fetchone() is not None
            if not visible:
                # Waypoint photo references are public attachments, regardless
                # of which member owns the uploaded asset.
                visible = any(
                    key in json.loads(item['photo_ids'])
                    for item in db.execute('SELECT photo_ids FROM waypoints'))
            if not visible:
                not_found()
            return bytes(row['png'])

    def save_profile(self, actor, body):
        name = text(body.get('name'), 60)
        photo = identifier(body.get('photo_id'))
        with self.transaction() as db:
            self.owned_asset(db, actor, photo)
            db.execute(
                'UPDATE users SET name=?, photo_id=? WHERE id=?',
                (name, photo, actor))
            return {'user': self.user_value(db, self.user_row(db, actor))}

    def waypoints(self, actor):
        with self.transaction() as db:
            return {
                'waypoints': [
                    self.waypoint_value(row)
                    for row in db.execute('SELECT * FROM waypoints ORDER BY rowid')
                ]
            }

    def waypoint(self, actor, key):
        with self.transaction() as db:
            return {
                'waypoint': self.waypoint_value(self.waypoint_row(db, key)),
                'comments': [
                    self.comment_value(db, row)
                    for row in db.execute(
                        'SELECT * FROM comments WHERE waypoint_id=? ORDER BY rowid', (key,))
                ],
            }

    def create_waypoint(self, actor, body):
        name = text(body.get('name'), 80)
        lat = coordinate(body.get('lat'), 85)
        lon = coordinate(body.get('lon'), 180)
        photos = unique_ids(body.get('photo_ids'), 0, 4)
        with self.transaction() as db:
            self.complete(db, actor)
            for key in photos:
                self.owned_asset(db, actor, key)
            key = secrets.token_urlsafe(18)
            db.execute(
                'INSERT INTO waypoints VALUES (?,?,?,?,?,?,?)',
                (key, actor, name, lat, lon, json.dumps(photos), 0))
            return {'waypoint': self.waypoint_value(self.waypoint_row(db, key))}

    def edit_waypoint(self, actor, key, body):
        # Validate the request shape before doing any write.  Resource and
        # ownership checks below give the documented 404/403 results.
        lat = coordinate(body.get('lat'), 85)
        lon = coordinate(body.get('lon'), 180)
        expected = revision(body.get('revision'))
        with self.transaction() as db:
            row = self.waypoint_row(db, key)
            if row['owner_id'] != actor:
                raise Failure(403, 'forbidden')
            self.complete(db, actor)
            if row['revision'] != expected:
                conflict()
            if row['lat'] == lat and row['lon'] == lon:
                return {'waypoint': self.waypoint_value(row)}
            # BEGIN IMMEDIATE above makes this compare-and-update atomic.  The
            # WHERE clause also records the exact optimistic-concurrency rule.
            updated = db.execute(
                'UPDATE waypoints SET lat=?, lon=?, revision=revision+1 '
                'WHERE id=? AND revision=?',
                (lat, lon, key, expected)).rowcount
            if updated != 1:
                conflict()
            return {
                'waypoint': self.waypoint_value(self.waypoint_row(db, key))
            }

    def create_route(self, actor, body):
        title = text(body.get('title'), 80)
        keys = unique_ids(body.get('waypoint_ids'), 2, 40)
        with self.transaction() as db:
            self.complete(db, actor)
            for key in keys:
                self.waypoint_row(db, key)
            key = secrets.token_urlsafe(18)
            db.execute(
                'INSERT INTO routes VALUES (?,?,?,?)',
                (key, actor, title, json.dumps(keys)))
            return {'route': self.route_value(db, self.route_row(db, key), actor)}

    def routes(self, actor, sort='asc', query=''):
        if sort not in ('asc', 'desc') or not isinstance(query, str) or len(query) > 80:
            invalid()
        query = query.strip()
        folded_query = fold(query)
        with self.transaction() as db:
            rows = [
                (creation_order, self.route_value(db, row, actor))
                for creation_order, row in enumerate(db.execute('SELECT * FROM routes ORDER BY rowid'))
                if folded_query in fold(row['title'])
            ]
            # Build the two pin groups first.  Sorting each group separately
            # keeps pin precedence independent of title order.  Including the
            # creation ordinal in the key makes descending ties follow the
            # reverse-creation direction rather than remaining stable.
            pinned = [row for row in rows if row[1]['pinned']]
            unpinned = [row for row in rows if not row[1]['pinned']]
            reverse = sort == 'desc'
            pinned.sort(key=lambda row: (fold(row[1]['title']), row[0]), reverse=reverse)
            unpinned.sort(key=lambda row: (fold(row[1]['title']), row[0]), reverse=reverse)
            return {'routes': [row[1] for row in pinned + unpinned]}

    def route(self, actor, key):
        with self.transaction() as db:
            route = self.route_value(db, self.route_row(db, key), actor)
            return {
                'route': route,
                'waypoints': [
                    self.waypoint_value(self.waypoint_row(db, waypoint_id))
                    for waypoint_id in route['waypoint_ids']
                ],
            }

    def pin(self, actor, key, body):
        if type(body.get('pinned')) is not bool:
            invalid()
        pinned = body['pinned']
        with self.transaction() as db:
            self.route_row(db, key)
            self.complete(db, actor)
            if pinned:
                # The primary key makes this idempotent even if a caller
                # submits the same membership more than once.
                db.execute(
                    'INSERT OR IGNORE INTO pins (user_id, route_id) VALUES (?,?)',
                    (actor, key))
            else:
                db.execute(
                    'DELETE FROM pins WHERE user_id=? AND route_id=?',
                    (actor, key))
            return {'route': self.route_value(db, self.route_row(db, key), actor)}

    def status(self, actor, body):
        value = body.get('status')
        if not isinstance(value, str) or value not in ('planned', 'touring', 'completed'):
            invalid()
        with self.transaction() as db:
            self.complete(db, actor)
            db.execute('UPDATE users SET touring_status=? WHERE id=?', (value, actor))
            return {'user': self.user_value(db, self.user_row(db, actor))}

    def comment(self, actor, key, body):
        normalized = text(body.get('text'), 600)
        request_id = body.get('request_id')
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
            invalid()
        with self.transaction() as db:
            # Resolve the target before the idempotency key so unknown records
            # retain the public 404 contract.
            self.waypoint_row(db, key)
            self.complete(db, actor)
            existing = db.execute(
                'SELECT * FROM comments WHERE author_id=? AND request_id=?',
                (actor, request_id)).fetchone()
            if existing is not None:
                if existing['waypoint_id'] != key or existing['text'] != normalized:
                    conflict()
                return 200, {'comment': self.comment_value(db, existing)}

            comment_id = secrets.token_urlsafe(18)
            db.execute(
                'INSERT INTO comments VALUES (?,?,?,?,?)',
                (comment_id, key, actor, normalized, request_id))
            created = db.execute(
                'SELECT * FROM comments WHERE id=?', (comment_id,)).fetchone()
            return 201, {'comment': self.comment_value(db, created)}
