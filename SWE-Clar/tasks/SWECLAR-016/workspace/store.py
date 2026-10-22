"""Existing authenticated workspace; complete the new business workflows."""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading

import media


class Failure(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def invalid():
    raise Failure(400, 'invalid_request')


def text(value, limit):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        invalid()
    return value.strip()


def identifier(value):
    if not isinstance(value, str) or not value:
        invalid()
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


class Store:
    def __init__(self, database, uploads, fixture, provider):
        self.database = Path(database)
        self.uploads = Path(uploads)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.provider = provider
        self.lock = threading.RLock()
        self.sessions = {}
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS initialized (version INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE, salt TEXT, password TEXT, tone TEXT, goal TEXT, revision INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, owner TEXT, title TEXT, revision INTEGER, messages TEXT, advice TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, owner TEXT, label TEXT, kind TEXT, width INTEGER, height INTEGER, filename TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS rankings (id TEXT PRIMARY KEY, owner TEXT, items TEXT)')
            if db.execute('SELECT version FROM initialized').fetchone() is None:
                users = json.loads(Path(fixture).read_text())['users']
                for user in users:
                    salt = secrets.token_hex(16)
                    digest = self.password_hash(user['password'], salt)
                    db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)',
                               (user['id'], user['username'], salt, digest, 'neutral', 'clarity', 0))
                db.execute('INSERT INTO initialized VALUES (1)')

    @contextmanager
    def transaction(self):
        # Keep existing data updates atomic.
        with self.lock:
            db = sqlite3.connect(self.database, timeout=60)
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
    def password_hash(password, salt):
        return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 120000).hex()

    def login(self, body):
        if not isinstance(body.get('username'), str) or not isinstance(body.get('password'), str):
            invalid()
        with self.transaction() as db:
            user = db.execute('SELECT * FROM users WHERE username=?', (body['username'],)).fetchone()
            if user is None or not hmac.compare_digest(self.password_hash(body['password'], user['salt']), user['password']):
                raise Failure(401, 'unauthenticated')
            token = secrets.token_urlsafe(32)
            self.sessions[token] = user['id']
            return {'token': token, 'user': {'id': user['id'], 'username': user['username']}}

    def actor(self, authorization):
        with self.lock:
            token = authorization[7:] if authorization.startswith('Bearer ') else ''
            if token not in self.sessions:
                raise Failure(401, 'unauthenticated')
            return self.sessions[token]

    def logout(self, authorization):
        with self.lock:
            self.actor(authorization)
            del self.sessions[authorization[7:]]
        return {'ok': True}

    @staticmethod
    def profile(db, owner):
        row = db.execute('SELECT tone,goal,revision FROM users WHERE id=?', (owner,)).fetchone()
        return dict(row)

    @staticmethod
    def owned(db, table, owner, key):
        row = db.execute('SELECT * FROM ' + table + ' WHERE id=? AND owner=?', (key, owner)).fetchone()
        if row is None:
            raise Failure(404, 'not_found')
        return row

    @staticmethod
    def conversation_value(row):
        return {'id': row['id'], 'title': row['title'], 'revision': row['revision'],
                'messages': json.loads(row['messages']), 'advice': json.loads(row['advice'])}

    @staticmethod
    def asset_value(row):
        return {key: row[key] for key in ('id', 'label', 'kind', 'width', 'height')}

    def workspace(self, owner):
        with self.transaction() as db:
            conversations = [dict(row) for row in db.execute('SELECT id,title,revision FROM conversations WHERE owner=? ORDER BY rowid', (owner,))]
            assets = [self.asset_value(row) for row in db.execute('SELECT * FROM assets WHERE owner=? ORDER BY rowid', (owner,))]
            return {'profile': self.profile(db, owner), 'conversations': conversations, 'assets': assets}

    def conversation(self, owner, key):
        with self.transaction() as db:
            return {'conversation': self.conversation_value(self.owned(db, 'conversations', owner, key))}

    def create_conversation(self, owner, body):
        title = text(body.get('title'), 80)
        key = secrets.token_hex(16)
        with self.transaction() as db:
            db.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?)', (key, owner, title, 0, '[]', '[]'))
            return {'conversation': self.conversation_value(self.owned(db, 'conversations', owner, key))}

    def upload(self, owner, body):
        label = text(body.get('label'), 80)
        kind = body.get('kind')
        if kind not in ('screenshot', 'photo'):
            invalid()
        try:
            data, width, height = media.sanitize(body.get('image_base64'))
        except Exception:
            invalid()
        key = secrets.token_hex(16)
        filename = secrets.token_hex(24) + '.png'
        path = self.uploads / filename
        try:
            with self.transaction() as db:
                with path.open('xb') as stream:
                    stream.write(data)
                db.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?)', (key, owner, label, kind, width, height, filename))
                result = {'asset': self.asset_value(self.owned(db, 'assets', owner, key))}
            return result
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def image(self, owner, key):
        with self.transaction() as db:
            asset = self.owned(db, 'assets', owner, key)
            try:
                return media.read_asset(self.uploads, asset['filename'])
            except Exception:
                invalid()

    def save_profile(self, owner, body):
        tone, goal = text(body.get('tone'), 120), text(body.get('goal'), 120)
        revision = body.get('revision')
        if type(revision) is not int or revision < 0:
            invalid()
        # TODO: implement preference updates after clarification.
        raise Failure(501, 'not_implemented')

    def rankings(self, owner):
        with self.transaction() as db:
            return {'rankings': [{'id': row['id'], 'items': json.loads(row['items'])} for row in db.execute('SELECT * FROM rankings WHERE owner=? ORDER BY rowid', (owner,))]}

    def workflow(self, owner, operation, body):
        key = body.get('request_id')
        if not isinstance(key, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key) is None:
            invalid()
        if operation == 'extract':
            semantic = {'conversation_id': identifier(body.get('conversation_id')), 'asset_id': identifier(body.get('asset_id'))}
        elif operation == 'coach':
            semantic = {'conversation_id': identifier(body.get('conversation_id')), 'question': text(body.get('question'), 300)}
        elif operation == 'rank':
            ids = body.get('asset_ids')
            if not isinstance(ids, list) or not 1 <= len(ids) <= 6 or not all(isinstance(item, str) and item for item in ids) or len(set(ids)) != len(ids):
                invalid()
            semantic = {'asset_ids': ids}
        else:
            raise Failure(404, 'not_found')
        with self.transaction() as db:
            conversation = None
            assets = []
            if operation in ('extract', 'coach'):
                conversation = self.owned(db, 'conversations', owner, semantic['conversation_id'])
            ids = [semantic['asset_id']] if operation == 'extract' else semantic.get('asset_ids', [])
            for asset_id in ids:
                assets.append(self.owned(db, 'assets', owner, asset_id))
            if any(asset['kind'] != ('screenshot' if operation == 'extract' else 'photo') for asset in assets):
                invalid()
            if operation == 'extract':
                # TODO: clarify and implement request replay for workflows.
                return self.extract_into(db, conversation, assets[0])
            # TODO: implement the coaching and image-review workflows.
            raise Failure(501, 'not_implemented')

    def extract_into(self, db, row, asset):
        try:
            messages = media.extract(self.uploads, asset['filename'])
        except Exception:
            raise Failure(422, 'extraction_failed')
        value = self.conversation_value(row)
        value['messages'].extend(messages)
        value['revision'] += 1
        db.execute('UPDATE conversations SET messages=?,revision=? WHERE id=?', (encode(value['messages']), value['revision'], row['id']))
        return {'conversation': value}

