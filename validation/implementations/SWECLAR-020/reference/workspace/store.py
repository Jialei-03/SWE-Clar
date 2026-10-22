"""Durable attendance operations and authorization for the synthetic workspace."""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import threading


class Failure(Exception):
    """An expected HTTP failure represented by its status and public code."""

    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def text(value, limit=None):
    """Validate a required non-empty string from an application request."""
    if not isinstance(value, str) or not value:
        raise Failure(400, 'invalid_request')
    if limit is not None and len(value) > limit:
        raise Failure(400, 'invalid_request')
    try:
        value.encode('utf-8')
    except UnicodeError as error:
        raise Failure(400, 'invalid_request') from error
    return value


class Store:
    def __init__(self, path, fixture):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        # Sessions intentionally live only in this process.  Restarting the
        # application therefore expires every token without touching records.
        self.sessions = {}
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            salt TEXT NOT NULL,
            digest TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entities(
            kind TEXT,
            id TEXT,
            record TEXT NOT NULL,
            PRIMARY KEY(kind,id)
        );
        CREATE TABLE IF NOT EXISTS scans(
            id TEXT PRIMARY KEY,
            reading_id TEXT UNIQUE NOT NULL,
            record TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attendance(
            id TEXT PRIMARY KEY,
            scan_id TEXT UNIQUE NOT NULL,
            record TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inbox(
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            attendance_id TEXT NOT NULL,
            record TEXT NOT NULL,
            UNIQUE(user_id,attendance_id)
        );
        CREATE TABLE IF NOT EXISTS initialized(flag INTEGER PRIMARY KEY);
        ''')
        with self.transaction():
            if not self.db.execute('SELECT 1 FROM initialized').fetchone():
                data = json.loads(Path(fixture).read_text(encoding='utf-8'))
                for original in data['users']:
                    user = dict(original)
                    password = user.pop('password')
                    salt = secrets.token_hex(16)
                    digest = self.password(password, salt)
                    self.db.execute(
                        'INSERT INTO users VALUES(?,?,?,?)',
                        (user['id'], json.dumps(user, ensure_ascii=False), salt, digest),
                    )
                for kind in ['students', 'tags', 'devices', 'guardians']:
                    for original in data[kind]:
                        item = dict(original)
                        if kind == 'students':
                            item['presence'] = 'out'
                        key = item['uid'] if kind == 'tags' else item['id']
                        self.db.execute(
                            'INSERT INTO entities VALUES(?,?,?)',
                            (kind, key, json.dumps(item, ensure_ascii=False)),
                        )
                self.db.execute('INSERT INTO initialized VALUES(1)')

    @staticmethod
    def password(password, salt):
        return hashlib.pbkdf2_hmac(
            'sha256', password.encode('utf-8'), bytes.fromhex(salt), 120000
        ).hex()

    @contextmanager
    def transaction(self):
        """Serialize writes and roll back every expected or unexpected failure."""
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
            except BaseException:
                self.db.execute('ROLLBACK')
                raise
            else:
                self.db.execute('COMMIT')

    def entities(self, kind):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                'SELECT record FROM entities WHERE kind=? ORDER BY rowid', (kind,)
            )
        ]

    def entity(self, kind, key):
        row = self.db.execute(
            'SELECT record FROM entities WHERE kind=? AND id=?', (kind, key)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save_entity(self, kind, key, value):
        self.db.execute(
            'UPDATE entities SET record=? WHERE kind=? AND id=?',
            (json.dumps(value, ensure_ascii=False), kind, key),
        )

    @staticmethod
    def public_user(user):
        return {
            key: user[key]
            for key in ['id', 'username', 'role', 'class_ids', 'student_ids']
        }

    def login(self, body):
        username = text(body.get('username'))
        password = text(body.get('password'))
        with self.lock:
            for row in self.db.execute('SELECT * FROM users ORDER BY rowid'):
                user = json.loads(row['record'])
                if (
                    user['username'] == username
                    and user['role'] in ['teacher', 'administrator', 'parent']
                    and user['active']
                    and hmac.compare_digest(
                        self.password(password, row['salt']), row['digest']
                    )
                ):
                    # token_urlsafe(32) is generated from at least 32 random
                    # bytes and is never persisted or put in a public record.
                    token = secrets.token_urlsafe(32)
                    self.sessions[token] = user['id']
                    return {'token': token, 'user': self.public_user(user)}
        raise Failure(401, 'unauthenticated')

    def actor(self, authorization):
        with self.lock:
            token = authorization[7:] if authorization.startswith('Bearer ') else ''
            uid = self.sessions.get(token)
            row = self.db.execute(
                'SELECT record FROM users WHERE id=?', (uid,)
            ).fetchone()
            if not row:
                raise Failure(401, 'unauthenticated')
            user = json.loads(row['record'])
            if not user['active']:
                raise Failure(401, 'unauthenticated')
            return user

    def logout(self, authorization):
        with self.lock:
            token = authorization[7:] if authorization.startswith('Bearer ') else ''
            self.sessions.pop(token, None)
        return {'ok': True}

    @staticmethod
    def staff(user):
        if user['role'] not in ['teacher', 'administrator']:
            raise Failure(403, 'forbidden')

    @staticmethod
    def visible(user, student):
        return bool(student) and (
            user['role'] == 'administrator'
            or (
                user['role'] == 'teacher'
                and student['class_id'] in user['class_ids']
            )
            or (
                user['role'] == 'parent'
                and student['id'] in user['student_ids']
            )
        )

    def roster(self, user):
        with self.lock:
            students = [
                student
                for student in self.entities('students')
                if self.visible(user, student)
            ]
            visible_ids = {student['id'] for student in students}
            guardians = []
            tags = []
            devices = []
            if user['role'] != 'parent':
                for guardian in self.entities('guardians'):
                    links = [
                        student_id
                        for student_id in guardian['student_ids']
                        if student_id in visible_ids
                    ]
                    if links:
                        guardians.append({**guardian, 'student_ids': links})
                tags = [
                    tag
                    for tag in self.entities('tags')
                    if tag['student_id'] in visible_ids
                ]
                devices = self.entities('devices')
            return {
                'students': students,
                'guardians': guardians,
                'tags': tags,
                'devices': devices,
            }

    def set_active(self, user, kind, key, body):
        # The caller also performs this check before parsing the request body;
        # retaining it here keeps the storage method safe for direct callers.
        if user['role'] != 'administrator':
            raise Failure(403, 'forbidden')
        if type(body.get('active')) is not bool:
            raise Failure(400, 'invalid_request')
        with self.transaction():
            item = self.entity(kind, key)
            if item is None:
                raise Failure(404, 'not_found')
            item['active'] = body['active']
            self.save_entity(kind, key, item)
            return {('tag' if kind == 'tags' else 'guardian'): item}

    def scans(self, user):
        self.staff(user)
        with self.lock:
            result = []
            for row in self.db.execute('SELECT record FROM scans ORDER BY rowid'):
                scan = json.loads(row[0])
                student = self.entity('students', scan['student_id'])
                if self.visible(user, student):
                    result.append(scan)
            return {'scans': result}

    def scan(self, user, reading, direction):
        """Create or replay one pending scan for an immutable reader reading."""
        self.staff(user)
        with self.transaction():
            row = self.db.execute(
                'SELECT record FROM scans WHERE reading_id=?', (reading['id'],)
            ).fetchone()
            if row:
                scan = json.loads(row[0])
                student = self.entity('students', scan['student_id'])
                # Scope is checked even for replay and before direction conflict.
                if not self.visible(user, student):
                    raise Failure(404, 'not_found')
                if scan['direction'] != direction:
                    raise Failure(409, 'reading_conflict')
                return 200, {'scan': scan, 'student': student}

            device = self.entity('devices', reading['device_id'])
            if not device or not device['active']:
                raise Failure(422, 'inactive_device')
            tag = self.entity('tags', reading['uid'])
            if not tag or not tag['active']:
                raise Failure(422, 'inactive_tag')
            student = self.entity('students', tag['student_id'])
            if not self.visible(user, student):
                raise Failure(404, 'not_found')
            if reading['interaction'] != 'tap':
                raise Failure(422, 'intentional_tap_required')

            scan = {
                'id': secrets.token_urlsafe(18),
                'reading_id': reading['id'],
                'student_id': student['id'],
                'tag_uid': reading['uid'],
                'device_id': reading['device_id'],
                'direction': direction,
                'at': reading['at'],
                'state': 'pending',
                'created_by': user['id'],
                'attendance_id': None,
            }
            self.db.execute(
                'INSERT INTO scans VALUES(?,?,?)',
                (scan['id'], reading['id'], json.dumps(scan, ensure_ascii=False)),
            )
            return 201, {'scan': scan, 'student': student}

    @staticmethod
    def _recipient_value(body):
        # Omission and explicit null are the same public recipient intent.
        return body.get('recipient_id')

    @staticmethod
    def _validate_recipient_syntax(direction, body):
        """Return the normalized recipient or raise the public syntax error."""
        recipient = Store._recipient_value(body)
        if direction == 'in':
            if recipient is not None:
                raise Failure(400, 'invalid_request')
            return None
        # Check-out requires a non-empty string.  A missing key is represented
        # by None and deliberately has its own business error.
        if recipient is None:
            raise Failure(422, 'recipient_required')
        if not isinstance(recipient, str) or not recipient:
            raise Failure(400, 'invalid_request')
        try:
            recipient.encode('utf-8')
        except UnicodeError as error:
            raise Failure(400, 'invalid_request') from error
        return recipient

    def _completed_replay(self, scan, body):
        recipient = self._validate_recipient_syntax(scan['direction'], body)
        if recipient != scan['_stored_recipient']:
            raise Failure(409, 'confirmation_conflict')
        attendance_row = self.db.execute(
            'SELECT record FROM attendance WHERE scan_id=?', (scan['id'],)
        ).fetchone()
        # A completed scan is only written atomically with its attendance.  A
        # missing row can therefore only indicate externally damaged storage;
        # avoid manufacturing a second result in that case.
        if not attendance_row:
            raise Failure(404, 'not_found')
        return 200, {'attendance': json.loads(attendance_row[0])}

    def confirm(self, user, key, body):
        """Authorize and atomically complete a pending scan or replay it."""
        self.staff(user)
        with self.transaction():
            row = self.db.execute(
                'SELECT record FROM scans WHERE id=?', (key,)
            ).fetchone()
            if not row:
                raise Failure(404, 'not_found')
            scan = json.loads(row[0])
            student = self.entity('students', scan['student_id'])
            if not self.visible(user, student):
                raise Failure(404, 'not_found')

            if scan['state'] == 'completed':
                # Keep the stored recipient private to the implementation and
                # use the same replay path without re-checking old tag/device,
                # guardian activity, presence, or reading time.
                attendance_row = self.db.execute(
                    'SELECT record FROM attendance WHERE scan_id=?', (scan['id'],)
                ).fetchone()
                if not attendance_row:
                    raise Failure(404, 'not_found')
                attendance = json.loads(attendance_row[0])
                scan['_stored_recipient'] = attendance['recipient_id']
                return self._completed_replay(scan, body)

            # A pending scan is re-authorized against current fixture state.
            device = self.entity('devices', scan['device_id'])
            if not device or not device['active']:
                raise Failure(422, 'inactive_device')
            tag = self.entity('tags', scan['tag_uid'])
            if (
                not tag
                or not tag['active']
                or tag['student_id'] != scan['student_id']
            ):
                raise Failure(422, 'inactive_tag')

            recipient = self._validate_recipient_syntax(scan['direction'], body)
            if scan['direction'] == 'out':
                guardian = self.entity('guardians', recipient)
                if (
                    not guardian
                    or not guardian['active']
                    or scan['student_id'] not in guardian['student_ids']
                ):
                    raise Failure(422, 'unauthorized_recipient')

            # Attendance timestamps are immutable reader seconds.  The last
            # completion for this student is the sequence predecessor because
            # confirmations are serialized and timestamps cannot decrease.
            last = None
            for previous_row in self.db.execute(
                'SELECT record FROM attendance ORDER BY rowid DESC'
            ):
                previous = json.loads(previous_row[0])
                if previous['student_id'] == student['id']:
                    last = previous
                    break
            if last is not None and scan['at'] < last['at']:
                raise Failure(409, 'stale_reading')

            if scan['direction'] == 'in':
                if student['presence'] != 'out':
                    raise Failure(409, 'attendance_conflict')
            else:
                if student['presence'] != 'in':
                    raise Failure(409, 'attendance_conflict')

            attendance = {
                'id': secrets.token_urlsafe(18),
                'scan_id': scan['id'],
                'student_id': scan['student_id'],
                'tag_uid': scan['tag_uid'],
                'device_id': scan['device_id'],
                'direction': scan['direction'],
                'at': scan['at'],
                'confirmed_by': user['id'],
                'recipient_id': recipient,
                'method': 'simulated_tag_tap',
            }
            self.db.execute(
                'INSERT INTO attendance VALUES(?,?,?)',
                (
                    attendance['id'],
                    attendance['scan_id'],
                    json.dumps(attendance, ensure_ascii=False),
                ),
            )

            student['presence'] = scan['direction']
            self.save_entity('students', student['id'], student)
            scan['state'] = 'completed'
            scan['attendance_id'] = attendance['id']
            self.db.execute(
                'UPDATE scans SET record=? WHERE id=?',
                (json.dumps(scan, ensure_ascii=False), scan['id']),
            )

            # Each currently active parent receives its own durable copy.  The
            # user id is indexed in the table but intentionally absent from the
            # public InboxEntry shape.
            for user_row in self.db.execute('SELECT id,record FROM users ORDER BY rowid'):
                parent = json.loads(user_row['record'])
                if (
                    parent['role'] == 'parent'
                    and parent['active']
                    and student['id'] in parent['student_ids']
                ):
                    entry = {
                        'id': secrets.token_urlsafe(18),
                        'attendance_id': attendance['id'],
                        'student_id': attendance['student_id'],
                        'direction': attendance['direction'],
                        'at': attendance['at'],
                        'confirmed_by': attendance['confirmed_by'],
                        'recipient_id': attendance['recipient_id'],
                        'read': False,
                    }
                    self.db.execute(
                        'INSERT INTO inbox VALUES(?,?,?,?)',
                        (
                            entry['id'],
                            parent['id'],
                            attendance['id'],
                            json.dumps(entry, ensure_ascii=False),
                        ),
                    )

            return 201, {'attendance': attendance}

    def attendance(self, user):
        with self.lock:
            result = [
                json.loads(row[0])
                for row in self.db.execute('SELECT record FROM attendance ORDER BY rowid')
            ]
            return {
                'attendance': [
                    item
                    for item in result
                    if self.visible(user, self.entity('students', item['student_id']))
                ]
            }

    def inbox(self, user):
        if user['role'] != 'parent':
            raise Failure(403, 'forbidden')
        with self.lock:
            return {
                'entries': [
                    json.loads(row[0])
                    for row in self.db.execute(
                        'SELECT record FROM inbox WHERE user_id=? ORDER BY rowid',
                        (user['id'],),
                    )
                ]
            }

    def set_read(self, user, key, body):
        if user['role'] != 'parent':
            raise Failure(403, 'forbidden')
        if type(body.get('read')) is not bool:
            raise Failure(400, 'invalid_request')
        with self.transaction():
            row = self.db.execute(
                'SELECT record FROM inbox WHERE id=? AND user_id=?',
                (key, user['id']),
            ).fetchone()
            if not row:
                raise Failure(404, 'not_found')
            entry = json.loads(row[0])
            entry['read'] = body['read']
            self.db.execute(
                'UPDATE inbox SET record=? WHERE id=?',
                (json.dumps(entry, ensure_ascii=False), key),
            )
            return {'entry': entry}
