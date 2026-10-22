"""Durable synthetic attendance operations with transactional confirmation."""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import threading


class Failure(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def text(value, limit=100):
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        raise Failure(400, 'invalid_request')
    return value


class Store:
    def __init__(self, path, fixture):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock(); self.sessions = {}
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, record TEXT NOT NULL, salt TEXT NOT NULL, digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS entities(kind TEXT, id TEXT, record TEXT NOT NULL, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY, reading_id TEXT UNIQUE NOT NULL, record TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attendance(id TEXT PRIMARY KEY, scan_id TEXT UNIQUE NOT NULL, record TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, attendance_id TEXT NOT NULL, record TEXT NOT NULL, UNIQUE(user_id,attendance_id));
        CREATE TABLE IF NOT EXISTS initialized(flag INTEGER PRIMARY KEY);
        ''')
        with self.transaction():
            if not self.db.execute('SELECT 1 FROM initialized').fetchone():
                data = json.loads(Path(fixture).read_text())
                for original in data['users']:
                    user = dict(original); password = user.pop('password'); salt = secrets.token_hex(16)
                    digest = self.password(password, salt)
                    self.db.execute('INSERT INTO users VALUES(?,?,?,?)', (user['id'], json.dumps(user), salt, digest))
                for kind in ['students', 'tags', 'devices', 'guardians']:
                    for original in data[kind]:
                        item = dict(original)
                        if kind == 'students': item['presence'] = 'out'
                        self.db.execute('INSERT INTO entities VALUES(?,?,?)', (kind, item['uid' if kind == 'tags' else 'id'], json.dumps(item)))
                self.db.execute('INSERT INTO initialized VALUES(1)')

    @staticmethod
    def password(password, salt):
        return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 120000).hex()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try: yield
            except BaseException:
                self.db.execute('ROLLBACK'); raise
            else: self.db.execute('COMMIT')

    def entities(self, kind):
        return [json.loads(r[0]) for r in self.db.execute('SELECT record FROM entities WHERE kind=? ORDER BY rowid', (kind,))]

    def entity(self, kind, key):
        row = self.db.execute('SELECT record FROM entities WHERE kind=? AND id=?', (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def save_entity(self, kind, key, value):
        self.db.execute('UPDATE entities SET record=? WHERE kind=? AND id=?', (json.dumps(value), kind, key))

    @staticmethod
    def public_user(user):
        return {k: user[k] for k in ['id', 'username', 'role', 'class_ids', 'student_ids']}

    def login(self, body):
        username, password = text(body.get('username')), text(body.get('password'), 1000)
        with self.lock:
            for row in self.db.execute('SELECT * FROM users ORDER BY rowid'):
                user = json.loads(row['record'])
                if user['username'] == username and user['active'] and hmac.compare_digest(self.password(password, row['salt']), row['digest']):
                    token = secrets.token_urlsafe(32); self.sessions[token] = user['id']
                    return {'token': token, 'user': self.public_user(user)}
        raise Failure(401, 'unauthenticated')

    def actor(self, authorization):
        with self.lock:
            key = authorization[7:] if authorization.startswith('Bearer ') else ''
            uid = self.sessions.get(key)
            row = self.db.execute('SELECT record FROM users WHERE id=?', (uid,)).fetchone()
            if not row: raise Failure(401, 'unauthenticated')
            user = json.loads(row[0])
            if not user['active']: raise Failure(401, 'unauthenticated')
            return user

    def logout(self, authorization):
        with self.lock: self.sessions.pop(authorization[7:], None)
        return {'ok': True}

    @staticmethod
    def staff(user):
        if user['role'] not in ['teacher', 'administrator']: raise Failure(403, 'forbidden')

    @staticmethod
    def visible(user, student):
        return bool(student) and (user['role'] == 'administrator' or
            (user['role'] == 'teacher' and student['class_id'] in user['class_ids']) or
            (user['role'] == 'parent' and student['id'] in user['student_ids']))

    def roster(self, user):
        with self.lock:
            students = [s for s in self.entities('students') if self.visible(user, s)]
            ids = {s['id'] for s in students}; guardians = []; tags = []; devices = []
            if user['role'] != 'parent':
                for g in self.entities('guardians'):
                    links = [s for s in g['student_ids'] if s in ids]
                    if links: guardians.append({**g, 'student_ids': links})
                tags = [t for t in self.entities('tags') if t['student_id'] in ids]
                devices = self.entities('devices')
            return {'students': students, 'guardians': guardians, 'tags': tags, 'devices': devices}

    def set_active(self, user, kind, key, body):
        if user['role'] != 'administrator': raise Failure(403, 'forbidden')
        if type(body.get('active')) is not bool: raise Failure(400, 'invalid_request')
        with self.transaction():
            item = self.entity(kind, key)
            if item is None: raise Failure(404, 'not_found')
            item['active'] = body['active']; self.save_entity(kind, key, item)
            return {('tag' if kind == 'tags' else 'guardian'): item}

    def scans(self, user):
        self.staff(user)
        with self.lock:
            result = []
            for row in self.db.execute('SELECT record FROM scans ORDER BY rowid'):
                scan = json.loads(row[0])
                if self.visible(user, self.entity('students', scan['student_id'])): result.append(scan)
            return {'scans': result}

    def scan(self, user, reading, direction):
        self.staff(user)
        with self.transaction():
            row = self.db.execute('SELECT record FROM scans WHERE reading_id=?', (reading['id'],)).fetchone()
            if row:
                scan = json.loads(row[0]); student = self.entity('students', scan['student_id'])
                if not self.visible(user, student): raise Failure(404, 'not_found')
                if scan['direction'] != direction: raise Failure(409, 'reading_conflict')
                return 200, {'scan': scan, 'student': student}
            device = self.entity('devices', reading['device_id'])
            if not device or not device['active']: raise Failure(422, 'inactive_device')
            tag = self.entity('tags', reading['uid'])
            if not tag or not tag['active']: raise Failure(422, 'inactive_tag')
            student = self.entity('students', tag['student_id'])
            if not self.visible(user, student): raise Failure(404, 'not_found')
            if reading['interaction'] != 'tap': raise Failure(422, 'intentional_tap_required')
            scan = {'id': secrets.token_urlsafe(18), 'reading_id': reading['id'], 'student_id': student['id'],
                    'tag_uid': reading['uid'], 'device_id': reading['device_id'], 'direction': direction,
                    'at': reading['at'], 'state': 'pending', 'created_by': user['id'], 'attendance_id': None}
            self.db.execute('INSERT INTO scans VALUES(?,?,?)', (scan['id'], reading['id'], json.dumps(scan)))
            return 201, {'scan': scan, 'student': student}

    def confirm(self, user, key, body):
        self.staff(user)
        raise Failure(501, 'not_implemented')

    def attendance(self, user):
        with self.lock:
            result = [json.loads(r[0]) for r in self.db.execute('SELECT record FROM attendance ORDER BY rowid')]
            return {'attendance': [r for r in result if self.visible(user, self.entity('students', r['student_id']))]}

    def inbox(self, user):
        if user['role'] != 'parent': raise Failure(403, 'forbidden')
        with self.lock:
            return {'entries': [json.loads(r[0]) for r in self.db.execute('SELECT record FROM inbox WHERE user_id=? ORDER BY rowid', (user['id'],))]}

    def set_read(self, user, key, body):
        if user['role'] != 'parent': raise Failure(403, 'forbidden')
        raise Failure(501, 'not_implemented')
