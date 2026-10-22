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
MINUTE = 60_000
TIME_LIMIT = 4_102_444_800_000
APPOINTMENT_FIELDS = (
    'id', 'patient_id', 'clinic_id', 'provider_id', 'slot_id',
    'start_ms', 'end_ms', 'status', 'revision', 'cancel_reason',
    'created_at_ms', 'updated_at_ms',
)


class Rejected(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def reject(status, code):
    raise Rejected(status, code)


def identifier(value):
    """Validate a caller-supplied identifier and return it unchanged."""
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        reject(400, 'invalid_request')
    return value


def public_user(row):
    return {key: row[key] for key in ('id', 'label', 'role', 'clinic_id')}


def public_appointment(row):
    return {key: row[key] for key in APPOINTMENT_FIELDS}


def appointment_path_id(value):
    """Appointment IDs are server-created opaque, non-empty path segments."""
    if not isinstance(value, str) or not value:
        reject(404, 'not_found')
    return value


class Store:
    def __init__(self, database, fixture, clock_file):
        self.database = Path(database)
        self.clock_file = Path(clock_file)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        # Validate the supplied infrastructure clock before opening the store.
        self.now()
        self.initialize(json.loads(Path(fixture).read_text()))

    def now(self):
        value = json.loads(self.clock_file.read_text())['now_ms']
        if type(value) is not int or not 0 <= value <= TIME_LIMIT:
            raise ValueError('Invalid benchmark clock')
        return value

    @contextmanager
    def connect(self, write=False):
        # A short-lived connection per operation keeps transactions independent
        # across HTTP worker threads and makes service restarts unremarkable.
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=10000')
        try:
            if write:
                # BEGIN IMMEDIATE serializes all state-changing scheduling
                # operations before they inspect occupancy or revisions.
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except Exception:
            try:
                db.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            db.close()

    def initialize(self, fixture):
        # Schema creation is itself transactional.  CREATE IF NOT EXISTS also
        # upgrades a database made by an earlier version without reseeding it.
        with self.connect(write=True) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS metadata(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS clinics(
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS providers(
                    id TEXT PRIMARY KEY,
                    clinic_id TEXT NOT NULL REFERENCES clinics(id),
                    label TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users(
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('patient','staff')),
                    clinic_id TEXT REFERENCES clinics(id),
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions(
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS slots(
                    id TEXT PRIMARY KEY,
                    clinic_id TEXT NOT NULL REFERENCES clinics(id),
                    provider_id TEXT NOT NULL REFERENCES providers(id),
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS appointments(
                    id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL REFERENCES users(id),
                    clinic_id TEXT NOT NULL REFERENCES clinics(id),
                    provider_id TEXT NOT NULL REFERENCES providers(id),
                    slot_id TEXT NOT NULL REFERENCES slots(id),
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','cancelled')),
                    revision INTEGER NOT NULL,
                    cancel_reason TEXT,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS booking_replays(
                    patient_id TEXT NOT NULL REFERENCES users(id),
                    request_id TEXT NOT NULL,
                    slot_id TEXT NOT NULL REFERENCES slots(id),
                    appointment_id TEXT NOT NULL REFERENCES appointments(id),
                    PRIMARY KEY(patient_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS move_replays(
                    actor_id TEXT NOT NULL REFERENCES users(id),
                    operation_id TEXT NOT NULL,
                    appointment_id TEXT NOT NULL REFERENCES appointments(id),
                    target_slot_id TEXT NOT NULL REFERENCES slots(id),
                    expected_revision INTEGER NOT NULL,
                    PRIMARY KEY(actor_id, operation_id)
                );
                CREATE INDEX IF NOT EXISTS appointments_patient_order
                    ON appointments(patient_id, start_ms, id);
                CREATE INDEX IF NOT EXISTS appointments_clinic_order
                    ON appointments(clinic_id, start_ms, id);
                CREATE INDEX IF NOT EXISTS appointments_slot_status
                    ON appointments(slot_id, status);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_appointment_per_slot
                    ON appointments(slot_id) WHERE status='active';
            ''')

        # The metadata marker is the only seed guard.  In particular, a
        # restart with a fixture file never resets appointments, slots or
        # sessions already present in this database.
        with self.connect(write=True) as db:
            if db.execute("SELECT 1 FROM metadata WHERE key='initialized'").fetchone():
                return
            for row in fixture['clinics']:
                db.execute('INSERT INTO clinics VALUES(?,?)', (row['id'], row['label']))
            for row in fixture['providers']:
                db.execute('INSERT INTO providers VALUES(?,?,?)',
                           (row['id'], row['clinic_id'], row['label']))
            for row in fixture['users']:
                salt = secrets.token_bytes(16)
                password_hash = hashlib.scrypt(
                    row['password'].encode('utf-8'), salt=salt,
                    n=16384, r=8, p=1,
                ).hex()
                db.execute(
                    'INSERT INTO users VALUES(?,?,?,?,?,?,?)',
                    (row['id'], row['username'], row['label'], row['role'],
                     row['clinic_id'], salt.hex(), password_hash),
                )
            for row in fixture['slots']:
                provider = db.execute(
                    'SELECT id, clinic_id FROM providers WHERE id=?',
                    (row['provider_id'],),
                ).fetchone()
                if provider is None:
                    # A supplied fixture is expected to be valid; fail startup
                    # transactionally rather than creating a malformed store.
                    raise sqlite3.IntegrityError('fixture provider is missing')
                db.execute(
                    'INSERT INTO slots VALUES(?,?,?,?,?)',
                    (row['id'], provider['clinic_id'], provider['id'],
                     row['start_ms'], row['start_ms'] + DURATION),
                )
            db.execute("INSERT INTO metadata VALUES('initialized','1')")

    def login(self, body):
        username, password = body.get('username'), body.get('password')
        if not isinstance(username, str) or not isinstance(password, str):
            reject(400, 'invalid_request')
        with self.connect(write=True) as db:
            row = db.execute(
                'SELECT * FROM users WHERE username=?', (username,)
            ).fetchone()
            # Hash a missing-user password with a real salt too, so the
            # response does not disclose whether the username exists.
            salt = bytes.fromhex(row['salt']) if row else secrets.token_bytes(16)
            actual = hashlib.scrypt(
                password.encode('utf-8'), salt=salt,
                n=16384, r=8, p=1,
            ).hex()
            if row is None or not hmac.compare_digest(actual, row['password_hash']):
                reject(401, 'invalid_credentials')
            token = secrets.token_hex(32)  # 32 secure random bytes
            token_hash = hashlib.sha256(token.encode('ascii')).hexdigest()
            db.execute(
                'INSERT INTO sessions VALUES(?,?)', (token_hash, row['id'])
            )
            return {'token': token, 'user': public_user(row)}

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def actor(self, token):
        if not isinstance(token, str) or not token:
            reject(401, 'unauthenticated')
        with self.connect() as db:
            row = db.execute(
                '''SELECT u.* FROM users u
                   JOIN sessions s ON s.user_id=u.id
                   WHERE s.token_hash=?''',
                (self.token_hash(token),),
            ).fetchone()
            if row is None:
                reject(401, 'unauthenticated')
            return public_user(row)

    def logout(self, token):
        with self.connect(write=True) as db:
            db.execute(
                'DELETE FROM sessions WHERE token_hash=?',
                (self.token_hash(token),),
            )
        return {'ok': True}

    def catalog(self):
        with self.connect() as db:
            clinics = [dict(row) for row in db.execute(
                'SELECT id, label FROM clinics ORDER BY id'
            )]
            providers = [dict(row) for row in db.execute(
                'SELECT id, clinic_id, label FROM providers ORDER BY id'
            )]
            return {'clinics': clinics, 'providers': providers, 'now_ms': self.now()}

    def publish(self, actor, body):
        # Role validation precedes provider lookup: patients cannot use this
        # endpoint to probe the provider directory or publish cross-clinic.
        if actor['role'] != 'staff':
            reject(403, 'forbidden')
        slot_id = identifier(body.get('id'))
        provider_id = identifier(body.get('provider_id'))
        start = body.get('start_ms')
        if (type(start) is not int or start % MINUTE != 0 or
                start < 0 or start + DURATION > TIME_LIMIT):
            reject(400, 'invalid_request')
        with self.connect(write=True) as db:
            provider = db.execute(
                'SELECT id, clinic_id FROM providers WHERE id=?',
                (provider_id,),
            ).fetchone()
            if provider is None:
                reject(404, 'not_found')
            if provider['clinic_id'] != actor['clinic_id']:
                reject(403, 'forbidden')
            now = self.now()
            if start <= now:
                reject(400, 'invalid_request')
            end = start + DURATION
            overlapping = db.execute(
                '''SELECT 1 FROM slots
                   WHERE id=? OR (provider_id=? AND start_ms<? AND end_ms>?)
                   LIMIT 1''',
                (slot_id, provider_id, end, start),
            ).fetchone()
            if overlapping is not None:
                reject(409, 'conflict')
            db.execute(
                'INSERT INTO slots VALUES(?,?,?,?,?)',
                (slot_id, provider['clinic_id'], provider_id, start, end),
            )
            row = db.execute('SELECT * FROM slots WHERE id=?', (slot_id,)).fetchone()
            return {'slot': dict(row)}

    def availability(self, query):
        # The endpoint has one required filter and one optional filter.  Do
        # not let arbitrary query parameters become an authorization escape
        # hatch, while retaining the documented empty-result behavior.
        if any(key not in ('clinic_id', 'provider_id') for key in query):
            reject(400, 'invalid_request')
        clinic = identifier(query.get('clinic_id'))
        provider = query.get('provider_id')
        if provider is not None:
            provider = identifier(provider)
        with self.connect() as db:
            if not db.execute(
                'SELECT 1 FROM clinics WHERE id=?', (clinic,)
            ).fetchone():
                reject(404, 'not_found')
            if provider is not None:
                row = db.execute(
                    'SELECT id, clinic_id FROM providers WHERE id=?',
                    (provider,),
                ).fetchone()
                if row is None:
                    reject(404, 'not_found')
                if row['clinic_id'] != clinic:
                    reject(400, 'invalid_request')
            now = self.now()
            rows = db.execute(
                '''SELECT s.id, s.clinic_id, s.provider_id, s.start_ms, s.end_ms
                   FROM slots s
                   WHERE s.clinic_id=?
                     AND (? IS NULL OR s.provider_id=?)
                     AND s.start_ms>?
                     AND NOT EXISTS(
                       SELECT 1 FROM appointments a
                       WHERE a.slot_id=s.id AND a.status='active'
                     )
                   ORDER BY s.start_ms, s.id''',
                (clinic, provider, provider, now),
            )
            return {'slots': [dict(row) for row in rows]}

    def authorized_appointment(self, db, actor, appointment_id):
        """Return an appointment only inside the authenticated actor's scope."""
        appointment_id = appointment_path_id(appointment_id)
        row = db.execute(
            'SELECT * FROM appointments WHERE id=?', (appointment_id,)
        ).fetchone()
        if row is None:
            reject(404, 'not_found')
        allowed = (
            (actor['role'] == 'patient' and row['patient_id'] == actor['id']) or
            (actor['role'] == 'staff' and row['clinic_id'] == actor['clinic_id'])
        )
        if not allowed:
            # Unknown and foreign records deliberately have the same outcome.
            reject(404, 'not_found')
        return row

    def appointments(self, actor):
        with self.connect() as db:
            if actor['role'] == 'patient':
                rows = db.execute(
                    '''SELECT * FROM appointments
                       WHERE patient_id=?
                       ORDER BY start_ms, id''',
                    (actor['id'],),
                )
            else:
                rows = db.execute(
                    '''SELECT * FROM appointments
                       WHERE clinic_id=?
                       ORDER BY start_ms, id''',
                    (actor['clinic_id'],),
                )
            return {'appointments': [public_appointment(row) for row in rows]}

    def appointment(self, actor, appointment_id):
        with self.connect() as db:
            row = self.authorized_appointment(db, actor, appointment_id)
            return {'appointment': public_appointment(row)}

    @staticmethod
    def _appointment_id():
        # A server-owned opaque ID; unlike caller IDs it has no policy meaning.
        return secrets.token_hex(16)

    def book(self, actor, body):
        if actor['role'] != 'patient':
            reject(403, 'forbidden')
        request_id = identifier(body.get('request_id'))
        slot_id = identifier(body.get('slot_id'))
        with self.connect(write=True) as db:
            now = self.now()
            replay = db.execute(
                '''SELECT slot_id, appointment_id FROM booking_replays
                   WHERE patient_id=? AND request_id=?''',
                (actor['id'], request_id),
            ).fetchone()
            if replay is not None:
                if replay['slot_id'] != slot_id:
                    reject(409, 'conflict')
                row = db.execute(
                    'SELECT * FROM appointments WHERE id=?',
                    (replay['appointment_id'],),
                ).fetchone()
                if row is None:
                    # This can only indicate a damaged store; never create a
                    # second booking or expose an incomplete replay.
                    reject(500, 'storage_error')
                return 200, {'appointment': public_appointment(row)}

            slot = db.execute(
                'SELECT * FROM slots WHERE id=?', (slot_id,)
            ).fetchone()
            if slot is None:
                reject(404, 'not_found')
            if slot['start_ms'] <= now:
                reject(409, 'conflict')
            if db.execute(
                '''SELECT 1 FROM appointments
                   WHERE slot_id=? AND status='active' LIMIT 1''',
                (slot_id,),
            ).fetchone() is not None:
                reject(409, 'conflict')

            appointment_id = self._appointment_id()
            # The random ID collision is extraordinarily unlikely, but retry
            # the ID insert without changing the transaction's business time.
            for _ in range(4):
                try:
                    db.execute(
                        '''INSERT INTO appointments
                           (id, patient_id, clinic_id, provider_id, slot_id,
                            start_ms, end_ms, status, revision, cancel_reason,
                            created_at_ms, updated_at_ms)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (appointment_id, actor['id'], slot['clinic_id'],
                         slot['provider_id'], slot['id'], slot['start_ms'],
                         slot['end_ms'], 'active', 1, None, now, now),
                    )
                    break
                except sqlite3.IntegrityError:
                    # Any other integrity failure should still be reported as a
                    # storage failure rather than silently changing semantics.
                    if db.execute(
                        'SELECT 1 FROM appointments WHERE id=?',
                        (appointment_id,),
                    ).fetchone() is not None:
                        appointment_id = self._appointment_id()
                        continue
                    raise
            else:
                raise sqlite3.IntegrityError('could not allocate appointment id')

            db.execute(
                '''INSERT INTO booking_replays
                   (patient_id, request_id, slot_id, appointment_id)
                   VALUES(?,?,?,?)''',
                (actor['id'], request_id, slot['id'], appointment_id),
            )
            row = db.execute(
                'SELECT * FROM appointments WHERE id=?',
                (appointment_id,),
            ).fetchone()
            return 201, {'appointment': public_appointment(row)}

    @staticmethod
    def cancellation_reason(body):
        reason = body.get('reason')
        if not isinstance(reason, str):
            reject(400, 'invalid_request')
        reason = reason.strip()
        if not 1 <= len(reason) <= 200:
            reject(400, 'invalid_request')
        return reason

    def cancel(self, actor, appointment_id, body):
        with self.connect(write=True) as db:
            now = self.now()
            # Scope is checked before inspecting cancellation state or applying
            # reason validation, so foreign and unknown IDs remain indistinct.
            row = self.authorized_appointment(db, actor, appointment_id)
            reason = self.cancellation_reason(body)
            if row['status'] == 'cancelled':
                # A valid later reason is an idempotent replay, not an update.
                return {'appointment': public_appointment(row)}
            if row['start_ms'] <= now:
                reject(409, 'conflict')
            updated = db.execute(
                '''UPDATE appointments
                   SET status='cancelled', cancel_reason=?, revision=revision+1,
                       updated_at_ms=?
                   WHERE id=? AND status='active' ''',
                (reason, now, row['id']),
            )
            if updated.rowcount != 1:
                # BEGIN IMMEDIATE normally makes this unreachable, but preserve
                # the legal conflict result if a future schema changes that.
                reject(409, 'conflict')
            row = db.execute(
                'SELECT * FROM appointments WHERE id=?', (row['id'],)
            ).fetchone()
            return {'appointment': public_appointment(row)}

    def move(self, actor, appointment_id, body):
        operation_id = identifier(body.get('operation_id'))
        target_slot_id = identifier(body.get('to_slot_id'))
        expected_revision = body.get('expected_revision')
        if type(expected_revision) is not int or expected_revision <= 0:
            reject(400, 'invalid_request')

        with self.connect(write=True) as db:
            now = self.now()
            # Authorization happens before replay lookup, target lookup, or any
            # response that could reveal a foreign appointment's history.
            row = self.authorized_appointment(db, actor, appointment_id)
            replay = db.execute(
                '''SELECT appointment_id, target_slot_id, expected_revision
                   FROM move_replays
                   WHERE actor_id=? AND operation_id=?''',
                (actor['id'], operation_id),
            ).fetchone()
            if replay is not None:
                if (replay['appointment_id'] != row['id'] or
                        replay['target_slot_id'] != target_slot_id or
                        replay['expected_revision'] != expected_revision):
                    reject(409, 'conflict')
                # A successful move replay always returns the current record,
                # not the old snapshot, even after a later operation.
                return {'appointment': public_appointment(row)}

            if row['status'] != 'active':
                reject(409, 'conflict')
            if row['start_ms'] <= now:
                reject(409, 'conflict')
            if row['revision'] != expected_revision:
                reject(409, 'conflict')

            target = db.execute(
                'SELECT * FROM slots WHERE id=?', (target_slot_id,)
            ).fetchone()
            if target is None:
                reject(404, 'not_found')
            if (target['id'] == row['slot_id'] or
                    target['clinic_id'] != row['clinic_id'] or
                    target['provider_id'] != row['provider_id'] or
                    target['start_ms'] <= now):
                reject(409, 'conflict')
            if db.execute(
                '''SELECT 1 FROM appointments
                   WHERE slot_id=? AND status='active' LIMIT 1''',
                (target_slot_id,),
            ).fetchone() is not None:
                reject(409, 'conflict')

            updated = db.execute(
                '''UPDATE appointments
                   SET slot_id=?, start_ms=?, end_ms=?, revision=revision+1,
                       updated_at_ms=?
                   WHERE id=? AND status='active' AND revision=?''',
                (target['id'], target['start_ms'], target['end_ms'], now,
                 row['id'], expected_revision),
            )
            if updated.rowcount != 1:
                reject(409, 'conflict')
            db.execute(
                '''INSERT INTO move_replays
                   (actor_id, operation_id, appointment_id, target_slot_id,
                    expected_revision)
                   VALUES(?,?,?,?,?)''',
                (actor['id'], operation_id, row['id'], target['id'],
                 expected_revision),
            )
            row = db.execute(
                'SELECT * FROM appointments WHERE id=?', (row['id'],)
            ).fetchone()
            return {'appointment': public_appointment(row)}
