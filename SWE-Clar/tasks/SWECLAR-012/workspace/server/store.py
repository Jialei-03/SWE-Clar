"""Synthetic scheduling persistence. No source customer code or data."""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3

IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
DURATION = 1_800_000
TIME_LIMIT = 4_102_444_800_000
APPOINTMENT_FIELDS = ('id', 'patient_id', 'clinic_id', 'provider_id', 'slot_id',
                      'start_ms', 'end_ms', 'status', 'revision', 'cancel_reason',
                      'created_at_ms', 'updated_at_ms')


class Rejected(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def reject(status, code):
    raise Rejected(status, code)


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        reject(400, 'invalid_request')
    return value


def public_user(row):
    return {key: row[key] for key in ('id', 'label', 'role', 'clinic_id')}


def public_appointment(row):
    return {key: row[key] for key in APPOINTMENT_FIELDS}


class Store:
    def __init__(self, database, fixture, clock_file):
        self.database = Path(database)
        self.clock_file = Path(clock_file)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.now()
        self.initialize(json.loads(Path(fixture).read_text()))

    def now(self):
        value = json.loads(self.clock_file.read_text())['now_ms']
        if type(value) is not int or not 0 <= value <= TIME_LIMIT:
            raise ValueError('Invalid benchmark clock')
        return value

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self, fixture):
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS clinics(id TEXT PRIMARY KEY, label TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS providers(
                    id TEXT PRIMARY KEY, clinic_id TEXT NOT NULL REFERENCES clinics(id), label TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS users(
                    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('patient','staff')), clinic_id TEXT REFERENCES clinics(id),
                    salt TEXT NOT NULL, password_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS slots(
                    id TEXT PRIMARY KEY, clinic_id TEXT NOT NULL REFERENCES clinics(id),
                    provider_id TEXT NOT NULL REFERENCES providers(id), start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS appointments(
                    id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES users(id),
                    clinic_id TEXT NOT NULL REFERENCES clinics(id), provider_id TEXT NOT NULL REFERENCES providers(id),
                    slot_id TEXT NOT NULL REFERENCES slots(id), start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','cancelled')), revision INTEGER NOT NULL,
                    cancel_reason TEXT, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL);
            ''')
        with self.connect(write=True) as db:
            if db.execute("SELECT 1 FROM metadata WHERE key='initialized'").fetchone():
                return
            for row in fixture['clinics']:
                db.execute('INSERT INTO clinics VALUES(?,?)', (row['id'], row['label']))
            for row in fixture['providers']:
                db.execute('INSERT INTO providers VALUES(?,?,?)', (row['id'], row['clinic_id'], row['label']))
            for row in fixture['users']:
                salt = secrets.token_bytes(16)
                password_hash = hashlib.scrypt(row['password'].encode(), salt=salt, n=16384, r=8, p=1).hex()
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)',
                           (row['id'], row['username'], row['label'], row['role'], row['clinic_id'], salt.hex(), password_hash))
            for row in fixture['slots']:
                provider = db.execute('SELECT * FROM providers WHERE id=?', (row['provider_id'],)).fetchone()
                db.execute('INSERT INTO slots VALUES(?,?,?,?,?)',
                           (row['id'], provider['clinic_id'], provider['id'], row['start_ms'], row['start_ms'] + DURATION))
            db.execute("INSERT INTO metadata VALUES('initialized','1')")

    def login(self, body):
        username, password = body.get('username'), body.get('password')
        if not isinstance(username, str) or not isinstance(password, str):
            reject(400, 'invalid_request')
        with self.connect(write=True) as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            salt = bytes.fromhex(row['salt']) if row else bytes(16)
            actual = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
            if row is None or not hmac.compare_digest(actual, row['password_hash']):
                reject(401, 'invalid_credentials')
            token = secrets.token_hex(32)
            db.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), row['id']))
            return {'token': token, 'user': public_user(row)}

    def actor(self, token):
        if not isinstance(token, str) or not token:
            reject(401, 'unauthenticated')
        with self.connect() as db:
            row = db.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=?',
                             (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if row is None:
                reject(401, 'unauthenticated')
            return public_user(row)

    def logout(self, token):
        with self.connect(write=True) as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
        return {'ok': True}

    def catalog(self):
        with self.connect() as db:
            return {'clinics': [dict(r) for r in db.execute('SELECT * FROM clinics ORDER BY id')],
                    'providers': [dict(r) for r in db.execute('SELECT * FROM providers ORDER BY id')], 'now_ms': self.now()}

    def publish(self, actor, body):
        if actor['role'] != 'staff':
            reject(403, 'forbidden')
        slot_id = identifier(body.get('id'))
        provider_id = identifier(body.get('provider_id'))
        start = body.get('start_ms')
        if type(start) is not int or start % 60000 or start < 0 or start + DURATION > TIME_LIMIT:
            reject(400, 'invalid_request')
        with self.connect(write=True) as db:
            provider = db.execute('SELECT * FROM providers WHERE id=?', (provider_id,)).fetchone()
            if provider is None:
                reject(404, 'not_found')
            if provider['clinic_id'] != actor['clinic_id']:
                reject(403, 'forbidden')
            if start <= self.now():
                reject(400, 'invalid_request')
            end = start + DURATION
            if db.execute('SELECT 1 FROM slots WHERE id=? OR (provider_id=? AND start_ms<? AND end_ms>?)',
                          (slot_id, provider_id, end, start)).fetchone():
                reject(409, 'conflict')
            db.execute('INSERT INTO slots VALUES(?,?,?,?,?)', (slot_id, provider['clinic_id'], provider_id, start, end))
            return {'slot': dict(db.execute('SELECT * FROM slots WHERE id=?', (slot_id,)).fetchone())}

    def availability(self, query):
        clinic = identifier(query.get('clinic_id'))
        provider = query.get('provider_id')
        if provider is not None:
            identifier(provider)
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM clinics WHERE id=?', (clinic,)).fetchone():
                reject(404, 'not_found')
            if provider is not None:
                row = db.execute('SELECT * FROM providers WHERE id=?', (provider,)).fetchone()
                if row is None:
                    reject(404, 'not_found')
                if row['clinic_id'] != clinic:
                    reject(400, 'invalid_request')
            rows = db.execute('''SELECT s.* FROM slots s
                WHERE s.clinic_id=? AND (? IS NULL OR s.provider_id=?) AND s.start_ms>?
                  AND NOT EXISTS(SELECT 1 FROM appointments a WHERE a.slot_id=s.id AND a.status='active')
                ORDER BY s.start_ms,s.id''', (clinic, provider, provider, self.now()))
            return {'slots': [dict(row) for row in rows]}

    def authorized_appointment(self, db, actor, appointment_id):
        reject(501, 'not_implemented')

    def appointments(self, actor):
        reject(501, 'not_implemented')

    def appointment(self, actor, appointment_id):
        reject(501, 'not_implemented')

    def book(self, actor, body):
        reject(501, 'not_implemented')

    def cancel(self, actor, appointment_id, body):
        reject(501, 'not_implemented')

    def move(self, actor, appointment_id, body):
        reject(501, 'not_implemented')
