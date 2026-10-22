"""Authenticated, durable route and waypoint records. Images are actual SQLite blobs."""
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
        self.status, self.code = status, code
        super().__init__(code)


def invalid(): raise Failure(400, 'invalid_request')
def conflict(): raise Failure(409, 'conflict')
def not_found(): raise Failure(404, 'not_found')
def text(value, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum: invalid()
    return value.strip()
def identifier(value):
    if not isinstance(value, str) or not value: invalid()
    return value
def revision(value):
    if type(value) is not int or value < 0: invalid()
    return value
def coordinate(value, limit):
    if type(value) not in (int, float) or not -limit <= value <= limit or not math.isfinite(value): invalid()
    return value
def unique_ids(value, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum: invalid()
    for item in value: identifier(item)
    if len(set(value)) != len(value): invalid()
    return value
def fold(value): return value.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))


class Store:
    def __init__(self, database, fixture):
        self.database = Path(database); self.database.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock(); self.sessions = {}
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS initialized (version INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY,username TEXT UNIQUE,salt TEXT,password TEXT,name TEXT,photo_id TEXT,touring_status TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY,owner_id TEXT,width INTEGER,height INTEGER,png BLOB)')
            db.execute('CREATE TABLE IF NOT EXISTS waypoints (id TEXT PRIMARY KEY,owner_id TEXT,name TEXT,lat REAL,lon REAL,photo_ids TEXT,revision INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS routes (id TEXT PRIMARY KEY,owner_id TEXT,title TEXT,waypoint_ids TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS pins (user_id TEXT,route_id TEXT,PRIMARY KEY(user_id,route_id))')
            db.execute('CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY,waypoint_id TEXT,author_id TEXT,text TEXT,request_id TEXT,UNIQUE(author_id,request_id))')
            if db.execute('SELECT version FROM initialized').fetchone() is None:
                for user in json.loads(Path(fixture).read_text())['users']:
                    salt = secrets.token_hex(16)
                    db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)', (user['id'], user['username'], salt, self.password(user['password'], salt), '', None, 'planned'))
                db.execute('INSERT INTO initialized VALUES (1)')

    @contextmanager
    def transaction(self):
        with self.lock:
            db = sqlite3.connect(self.database, timeout=30); db.row_factory = sqlite3.Row
            try:
                db.execute('BEGIN IMMEDIATE'); yield db; db.commit()
            except BaseException:
                db.rollback(); raise
            finally: db.close()

    @staticmethod
    def password(value, salt): return hashlib.pbkdf2_hmac('sha256', value.encode(), bytes.fromhex(salt), 120000).hex()
    @staticmethod
    def user_value(row):
        return {**{key: row[key] for key in ('id', 'username', 'name', 'photo_id', 'touring_status')}, 'profile_required': not bool(row['name'].strip() and row['photo_id'])}
    @staticmethod
    def waypoint_value(row): return {**dict(row), 'photo_ids': json.loads(row['photo_ids'])}
    @staticmethod
    def asset_value(row): return {'id': row['id'], 'width': row['width'], 'height': row['height'], 'url': '/api/assets/' + quote(row['id'], safe='')}
    @staticmethod
    def user_row(db, actor):
        row = db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone()
        if row is None: raise Failure(401, 'unauthenticated')
        return row
    def complete(self, db, actor):
        row = self.user_row(db, actor)
        if self.user_value(row)['profile_required']: raise Failure(403, 'profile_required')
        return row
    @staticmethod
    def waypoint_row(db, key):
        row = db.execute('SELECT * FROM waypoints WHERE id=?', (key,)).fetchone()
        if row is None: not_found()
        return row
    @staticmethod
    def route_row(db, key):
        row = db.execute('SELECT * FROM routes WHERE id=?', (key,)).fetchone()
        if row is None: not_found()
        return row
    @staticmethod
    def owned_asset(db, actor, key):
        row = db.execute('SELECT * FROM assets WHERE id=? AND owner_id=?', (key, actor)).fetchone()
        if row is None: not_found()
        return row
    @staticmethod
    def route_value(db, row, actor):
        pinned = db.execute('SELECT 1 FROM pins WHERE user_id=? AND route_id=?', (actor, row['id'])).fetchone() is not None
        return {**dict(row), 'waypoint_ids': json.loads(row['waypoint_ids']), 'pinned': pinned}
    def comment_value(self, db, row):
        author = self.user_row(db, row['author_id'])
        return {'id': row['id'], 'waypoint_id': row['waypoint_id'], 'text': row['text'],
                'author': {key: author[key] for key in ('id', 'name', 'photo_id')}}

    def login(self, body):
        if not isinstance(body.get('username'), str) or not isinstance(body.get('password'), str): invalid()
        with self.transaction() as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (body['username'],)).fetchone()
            if row is None or not hmac.compare_digest(self.password(body['password'], row['salt']), row['password']):
                raise Failure(401, 'unauthenticated')
            token = secrets.token_urlsafe(32); self.sessions[token] = row['id']
            return {'token': token, 'user': self.user_value(row)}

    def actor(self, authorization):
        token = authorization[7:] if authorization.startswith('Bearer ') else ''
        with self.lock:
            if token not in self.sessions: raise Failure(401, 'unauthenticated')
            return self.sessions[token]

    def logout(self, authorization):
        with self.lock:
            self.actor(authorization); del self.sessions[authorization[7:]]
        return {'ok': True}

    def me(self, actor):
        with self.transaction() as db: return {'user': self.user_value(self.user_row(db, actor))}

    def assets(self, actor):
        with self.transaction() as db:
            return {'assets': [self.asset_value(row) for row in db.execute('SELECT * FROM assets WHERE owner_id=? ORDER BY rowid', (actor,))]}

    def upload(self, actor, body):
        try: png, width, height = sanitize(body.get('png_base64'))
        except (ValueError, OSError, SyntaxError): invalid()
        with self.transaction() as db:
            key = secrets.token_urlsafe(18)
            db.execute('INSERT INTO assets VALUES (?,?,?,?,?)', (key, actor, width, height, png))
            return {'asset': self.asset_value(self.owned_asset(db, actor, key))}

    def asset(self, actor, key):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM assets WHERE id=?', (key,)).fetchone()
            if row is None: not_found()
            visible = row['owner_id'] == actor or db.execute('SELECT 1 FROM users WHERE photo_id=?', (key,)).fetchone() is not None
            if not visible: visible = any(key in json.loads(item['photo_ids']) for item in db.execute('SELECT photo_ids FROM waypoints'))
            if not visible: not_found()
            return bytes(row['png'])

    def save_profile(self, actor, body):
        name, photo = text(body.get('name'), 60), identifier(body.get('photo_id'))
        with self.transaction() as db:
            self.owned_asset(db, actor, photo)
            db.execute('UPDATE users SET name=?,photo_id=? WHERE id=?', (name, photo, actor))
            return {'user': self.user_value(self.user_row(db, actor))}

    def waypoints(self, actor):
        with self.transaction() as db:
            return {'waypoints': [self.waypoint_value(row) for row in db.execute('SELECT * FROM waypoints ORDER BY rowid')]}

    def waypoint(self, actor, key):
        with self.transaction() as db:
            return {'waypoint': self.waypoint_value(self.waypoint_row(db, key)),
                    'comments': [self.comment_value(db, row) for row in db.execute('SELECT * FROM comments WHERE waypoint_id=? ORDER BY rowid', (key,))]}

    def create_waypoint(self, actor, body):
        name = text(body.get('name'), 80)
        lat, lon = coordinate(body.get('lat'), 85), coordinate(body.get('lon'), 180)
        photos = unique_ids(body.get('photo_ids'), 0, 4)
        with self.transaction() as db:
            self.complete(db, actor)
            for key in photos: self.owned_asset(db, actor, key)
            key = secrets.token_urlsafe(18)
            db.execute('INSERT INTO waypoints VALUES (?,?,?,?,?,?,0)', (key, actor, name, lat, lon, json.dumps(photos)))
            return {'waypoint': self.waypoint_value(self.waypoint_row(db, key))}

    def edit_waypoint(self, actor, key, body):
        with self.transaction() as db:
            self.complete(db, actor)
            row = self.waypoint_row(db, key)
            if row['owner_id'] != actor: raise Failure(403, 'forbidden')
            # TODO: clarify and implement this persistent business behavior.
            raise Failure(501, 'not_implemented')

    def create_route(self, actor, body):
        title, keys = text(body.get('title'), 80), unique_ids(body.get('waypoint_ids'), 2, 40)
        with self.transaction() as db:
            self.complete(db, actor)
            for key in keys: self.waypoint_row(db, key)
            key = secrets.token_urlsafe(18)
            db.execute('INSERT INTO routes VALUES (?,?,?,?)', (key, actor, title, json.dumps(keys)))
            return {'route': self.route_value(db, self.route_row(db, key), actor)}

    def routes(self, actor, sort='asc', query=''):
        if sort not in ('asc', 'desc') or not isinstance(query, str) or len(query) > 80: invalid()
        with self.transaction() as db:
            rows = [self.route_value(db, row, actor) for row in db.execute('SELECT * FROM routes ORDER BY rowid') if fold(query.strip()) in fold(row['title'])]
            # TODO: clarify catalog ordering and personal pin precedence.
            return {'routes': rows}

    def route(self, actor, key):
        with self.transaction() as db:
            route = self.route_value(db, self.route_row(db, key), actor)
            return {'route': route, 'waypoints': [self.waypoint_value(self.waypoint_row(db, waypoint)) for waypoint in route['waypoint_ids']]}

    def pin(self, actor, key, body):
        with self.transaction() as db:
            self.complete(db, actor)
            self.route_row(db, key)
            # TODO: clarify and implement this persistent business behavior.
            raise Failure(501, 'not_implemented')

    def status(self, actor, body):
        with self.transaction() as db:
            self.complete(db, actor)
            # TODO: clarify and implement this persistent business behavior.
            raise Failure(501, 'not_implemented')

    def comment(self, actor, key, body):
        with self.transaction() as db:
            self.complete(db, actor)
            row = self.waypoint_row(db, key)
            # TODO: clarify and implement this persistent business behavior.
            raise Failure(501, 'not_implemented')
