"""Authenticated, durable conversation and image workspace state."""
from contextlib import contextmanager
import base64
import hashlib
import hmac
import json
import math
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
    """Validate and normalize a user-facing string."""
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        invalid()
    return value.strip()


def identifier(value):
    # Resource identifiers are opaque.  In particular, do not trim them or
    # interpret a caller supplied identifier as an owner.
    if not isinstance(value, str) or not value:
        invalid()
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


class Store:
    SYSTEM_PROMPT = 'Offer clear and respectful communication suggestions.'

    def __init__(self, database, uploads, fixture, provider):
        self.database = Path(database)
        self.uploads = Path(uploads)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.provider = provider

        # SQLite transactions serialize durable changes.  This lock also
        # protects the in-memory session table and the small workflow-lock map.
        self.lock = threading.RLock()
        self.sessions = {}
        self.workflow_locks = {}
        self.workflow_locks_lock = threading.Lock()

        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS initialized (version INTEGER)')
            db.execute(
                'CREATE TABLE IF NOT EXISTS users ('
                'id TEXT PRIMARY KEY, username TEXT UNIQUE, salt TEXT, password TEXT, '
                'tone TEXT, goal TEXT, revision INTEGER)')
            db.execute(
                'CREATE TABLE IF NOT EXISTS conversations ('
                'id TEXT PRIMARY KEY, owner TEXT, title TEXT, revision INTEGER, '
                'messages TEXT, advice TEXT)')
            db.execute(
                'CREATE TABLE IF NOT EXISTS assets ('
                'id TEXT PRIMARY KEY, owner TEXT, label TEXT, kind TEXT, '
                'width INTEGER, height INTEGER, filename TEXT)')
            db.execute(
                'CREATE TABLE IF NOT EXISTS rankings ('
                'id TEXT PRIMARY KEY, owner TEXT, items TEXT)')
            # A replay belongs to a stable application user, rather than to a
            # transient login token.  The primary key gives the namespace its
            # one-request-key-per-user semantics.
            db.execute(
                'CREATE TABLE IF NOT EXISTS workflow_replays ('
                'owner TEXT NOT NULL, request_id TEXT NOT NULL, operation TEXT NOT NULL, '
                'semantic TEXT NOT NULL, result TEXT NOT NULL, '
                'PRIMARY KEY (owner, request_id))')

            if db.execute('SELECT version FROM initialized').fetchone() is None:
                users = json.loads(Path(fixture).read_text())['users']
                for user in users:
                    salt = secrets.token_hex(16)
                    digest = self.password_hash(user['password'], salt)
                    db.execute(
                        'INSERT INTO users VALUES (?,?,?,?,?,?,?)',
                        (user['id'], user['username'], salt, digest,
                         'neutral', 'clarity', 0))
                db.execute('INSERT INTO initialized VALUES (1)')

    @contextmanager
    def transaction(self):
        # BEGIN IMMEDIATE makes each mutation all-or-nothing and lets the
        # application use one consistent SQLite locking policy for all threads.
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

    @contextmanager
    def workflow_guard(self, owner, request_id):
        """Serialize attempts sharing one user's request key.

        The guard is deliberately narrower than the database lock: unrelated
        users/actions may perform provider calls concurrently, while identical
        concurrent requests cannot both call OCR/provider or commit twice.
        """
        key = (owner, request_id)
        with self.workflow_locks_lock:
            entry = self.workflow_locks.get(key)
            if entry is None:
                entry = {'lock': threading.Lock(), 'users': 0}
                self.workflow_locks[key] = entry
            entry['users'] += 1
        lock = entry['lock']
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self.workflow_locks_lock:
                entry['users'] -= 1
                if entry['users'] == 0 and self.workflow_locks.get(key) is entry:
                    del self.workflow_locks[key]

    @staticmethod
    def password_hash(password, salt):
        return hashlib.pbkdf2_hmac(
            'sha256', password.encode(), bytes.fromhex(salt), 120000).hex()

    def login(self, body):
        if not isinstance(body.get('username'), str) or not isinstance(body.get('password'), str):
            invalid()
        with self.transaction() as db:
            user = db.execute(
                'SELECT * FROM users WHERE username=?', (body['username'],)).fetchone()
            if user is None or not hmac.compare_digest(
                    self.password_hash(body['password'], user['salt']), user['password']):
                raise Failure(401, 'unauthenticated')
            # token_urlsafe(32) is generated from 32 random bytes.
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
            token = authorization[7:] if authorization.startswith('Bearer ') else ''
            if token not in self.sessions:
                raise Failure(401, 'unauthenticated')
            del self.sessions[token]
        return {'ok': True}

    @staticmethod
    def profile(db, owner):
        row = db.execute(
            'SELECT tone,goal,revision FROM users WHERE id=?', (owner,)).fetchone()
        # owner always comes from an authenticated session, so this should be
        # present.  Keeping the failure non-leaky is useful for damaged stores.
        if row is None:
            raise Failure(401, 'unauthenticated')
        return dict(row)

    @staticmethod
    def owned(db, table, owner, key):
        # table is selected only from fixed internal call sites.
        row = db.execute(
            'SELECT * FROM ' + table + ' WHERE id=? AND owner=?', (key, owner)).fetchone()
        if row is None:
            raise Failure(404, 'not_found')
        return row

    @staticmethod
    def conversation_value(row):
        return {
            'id': row['id'],
            'title': row['title'],
            'revision': row['revision'],
            'messages': json.loads(row['messages']),
            'advice': json.loads(row['advice']),
        }

    @staticmethod
    def asset_value(row):
        return {key: row[key] for key in ('id', 'label', 'kind', 'width', 'height')}

    def workspace(self, owner):
        with self.transaction() as db:
            conversations = [
                dict(row) for row in db.execute(
                    'SELECT id,title,revision FROM conversations '
                    'WHERE owner=? ORDER BY rowid', (owner,))]
            assets = [
                self.asset_value(row) for row in db.execute(
                    'SELECT * FROM assets WHERE owner=? ORDER BY rowid', (owner,))]
            return {
                'profile': self.profile(db, owner),
                'conversations': conversations,
                'assets': assets,
            }

    def conversation(self, owner, key):
        with self.transaction() as db:
            return {'conversation': self.conversation_value(
                self.owned(db, 'conversations', owner, key))}

    def create_conversation(self, owner, body):
        title = text(body.get('title'), 80)
        key = secrets.token_hex(16)
        with self.transaction() as db:
            db.execute(
                'INSERT INTO conversations VALUES (?,?,?,?,?,?)',
                (key, owner, title, 0, '[]', '[]'))
            return {'conversation': self.conversation_value(
                self.owned(db, 'conversations', owner, key))}

    def upload(self, owner, body):
        label = text(body.get('label'), 80)
        kind = body.get('kind')
        if kind not in ('screenshot', 'photo'):
            invalid()
        try:
            data, width, height = media.sanitize(body.get('image_base64'))
        except Exception:
            # Decoding, complete verification, and canonicalization happen
            # before either a database row or a file is created.
            invalid()

        key = secrets.token_hex(16)
        filename = secrets.token_hex(24) + '.png'
        path = self.uploads / filename
        created = False
        try:
            with self.transaction() as db:
                with path.open('xb') as stream:
                    created = True
                    stream.write(data)
                db.execute(
                    'INSERT INTO assets VALUES (?,?,?,?,?,?,?)',
                    (key, owner, label, kind, width, height, filename))
                result = {'asset': self.asset_value(
                    self.owned(db, 'assets', owner, key))}
            return result
        except BaseException:
            # This also covers a commit failure: an unregistered generated file
            # must never be left behind after an invalid/failed upload.  Never
            # remove a pre-existing file if an exclusive create collided.
            if created:
                path.unlink(missing_ok=True)
            raise

    def image(self, owner, key):
        with self.transaction() as db:
            asset = self.owned(db, 'assets', owner, key)
            try:
                return media.read_asset(self.uploads, asset['filename'])
            except Exception:
                # A stored asset whose backing file is no longer a valid PNG is
                # not served as arbitrary bytes.
                raise Failure(404, 'not_found')

    def save_profile(self, owner, body):
        # Validate both values before beginning the update transaction.
        tone, goal = text(body.get('tone'), 120), text(body.get('goal'), 120)
        revision = body.get('revision')
        if type(revision) is not int or revision < 0:
            invalid()
        with self.transaction() as db:
            changed = db.execute(
                'UPDATE users SET tone=?, goal=?, revision=revision+1 '
                'WHERE id=? AND revision=?',
                (tone, goal, owner, revision)).rowcount
            if changed != 1:
                raise Failure(409, 'conflict')
            return {'profile': self.profile(db, owner)}

    def rankings(self, owner):
        with self.transaction() as db:
            return {
                'rankings': [
                    {'id': row['id'], 'items': json.loads(row['items'])}
                    for row in db.execute(
                        'SELECT * FROM rankings WHERE owner=? ORDER BY rowid', (owner,))]
            }

    @staticmethod
    def _request_id(value):
        if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value) is None:
            invalid()
        return value

    @staticmethod
    def _replay(db, owner, request_id, operation, semantic):
        row = db.execute(
            'SELECT operation,semantic,result FROM workflow_replays '
            'WHERE owner=? AND request_id=?', (owner, request_id)).fetchone()
        if row is None:
            return None
        try:
            previous_semantic = json.loads(row['semantic'])
            previous_result = json.loads(row['result'])
        except (TypeError, ValueError, json.JSONDecodeError):
            # This is internal durable corruption rather than a client input;
            # do not turn it into a new successful mutation.
            raise Failure(502, 'provider_failed')
        if row['operation'] != operation or previous_semantic != semantic:
            raise Failure(409, 'conflict')
        return previous_result

    @staticmethod
    def _save_replay(db, owner, request_id, operation, semantic, result):
        db.execute(
            'INSERT INTO workflow_replays '
            '(owner,request_id,operation,semantic,result) VALUES (?,?,?,?,?)',
            (owner, request_id, operation, encode(semantic), encode(result)))

    @staticmethod
    def _provider_failure():
        return Failure(502, 'provider_failed')

    def _call_provider(self, route, payload):
        try:
            return self.provider.request(route, payload)
        except Exception as error:
            # Provider status, transport, JSON, and protocol errors are all
            # intentionally exposed through the one public error contract.
            raise self._provider_failure() from error

    @staticmethod
    def _advice_from_response(response):
        if not isinstance(response, dict) or not isinstance(response.get('advice'), str):
            raise Failure(502, 'provider_failed')
        advice = response['advice'].strip()
        if not 1 <= len(advice) <= 4000:
            raise Failure(502, 'provider_failed')
        return advice

    @staticmethod
    def _scores_from_response(response, requested):
        if not isinstance(response, dict) or not isinstance(response.get('scores'), list):
            raise Failure(502, 'provider_failed')
        rows = response['scores']
        if len(rows) != len(requested):
            raise Failure(502, 'provider_failed')
        requested_set = set(requested)
        seen = set()
        parsed = []
        for row in rows:
            if not isinstance(row, dict):
                raise Failure(502, 'provider_failed')
            asset_id = row.get('asset_id')
            score = row.get('score')
            reasons = row.get('reasons')
            if (not isinstance(asset_id, str) or asset_id not in requested_set
                    or asset_id in seen):
                raise Failure(502, 'provider_failed')
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise Failure(502, 'provider_failed')
            try:
                finite = math.isfinite(score)
            except (TypeError, OverflowError, ValueError):
                finite = False
            if not finite or score < 0 or score > 100:
                raise Failure(502, 'provider_failed')
            if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
                raise Failure(502, 'provider_failed')
            seen.add(asset_id)
            # Make a fresh application-owned row and ignore harmless provider
            # extension fields.  The returned values themselves are retained.
            parsed.append({'asset_id': asset_id, 'score': score, 'reasons': list(reasons)})
        if seen != requested_set:
            raise Failure(502, 'provider_failed')
        parsed.sort(key=lambda item: (-item['score'], item['asset_id']))
        return parsed

    def workflow(self, owner, operation, body):
        request_id = self._request_id(body.get('request_id'))
        if operation == 'extract':
            semantic = {
                'conversation_id': identifier(body.get('conversation_id')),
                'asset_id': identifier(body.get('asset_id')),
            }
        elif operation == 'coach':
            semantic = {
                'conversation_id': identifier(body.get('conversation_id')),
                'question': text(body.get('question'), 300),
            }
        elif operation == 'rank':
            ids = body.get('asset_ids')
            if (not isinstance(ids, list) or not 1 <= len(ids) <= 6
                    or not all(isinstance(item, str) and item for item in ids)
                    or len(set(ids)) != len(ids)):
                invalid()
            # Copy the list so no caller-owned mutable value can change the
            # semantic payload while a request is being processed.
            semantic = {'asset_ids': list(ids)}
        else:
            raise Failure(404, 'not_found')

        with self.workflow_guard(owner, request_id):
            if operation == 'extract':
                return self._workflow_extract(owner, request_id, semantic)
            if operation == 'coach':
                return self._workflow_coach(owner, request_id, semantic)
            return self._workflow_rank(owner, request_id, semantic)

    def _workflow_extract(self, owner, request_id, semantic):
        with self.transaction() as db:
            conversation = self.owned(db, 'conversations', owner, semantic['conversation_id'])
            asset = self.owned(db, 'assets', owner, semantic['asset_id'])
            if asset['kind'] != 'screenshot':
                invalid()
            replay = self._replay(db, owner, request_id, 'extract', semantic)
            if replay is not None:
                return replay
            filename = asset['filename']

        # OCR is performed only after both resources and their kinds have been
        # authorized.  No caller-provided text enters this path.
        try:
            messages = media.extract(self.uploads, filename)
        except Exception as error:
            raise Failure(422, 'extraction_failed') from error

        with self.transaction() as db:
            # Re-read the conversation so concurrent, different workflow keys
            # append rather than overwrite one another's messages.
            current = self.owned(db, 'conversations', owner, semantic['conversation_id'])
            replay = self._replay(db, owner, request_id, 'extract', semantic)
            if replay is not None:
                return replay
            value = self.conversation_value(current)
            value['messages'].extend(messages)
            value['revision'] += 1
            db.execute(
                'UPDATE conversations SET messages=?,revision=? WHERE id=? AND owner=?',
                (encode(value['messages']), value['revision'], current['id'], owner))
            result = {'conversation': value}
            self._save_replay(db, owner, request_id, 'extract', semantic, result)
            return result

    def extract_into(self, db, row, asset):
        """Retain the starter's small extraction helper for internal callers."""
        try:
            messages = media.extract(self.uploads, asset['filename'])
        except Exception as error:
            raise Failure(422, 'extraction_failed') from error
        value = self.conversation_value(row)
        value['messages'].extend(messages)
        value['revision'] += 1
        db.execute(
            'UPDATE conversations SET messages=?,revision=? WHERE id=?',
            (encode(value['messages']), value['revision'], row['id']))
        return {'conversation': value}

    def _workflow_coach(self, owner, request_id, semantic):
        with self.transaction() as db:
            conversation = self.owned(db, 'conversations', owner, semantic['conversation_id'])
            stored_messages = json.loads(conversation['messages'])
            if not stored_messages:
                raise Failure(409, 'conflict')
            replay = self._replay(db, owner, request_id, 'coach', semantic)
            if replay is not None:
                return replay
            # Construct exactly the public text-only provider context.  Advice,
            # IDs, profile revision and any extra stored fields are excluded.
            messages = [
                {'sender': row['sender'], 'text': row['text']}
                for row in stored_messages]
            profile = self.profile(db, owner)
            profile_context = {'tone': profile['tone'], 'goal': profile['goal']}
            context_revision = conversation['revision']

        response = self._call_provider('/coach', {
            'system_prompt': self.SYSTEM_PROMPT,
            'profile': profile_context,
            'messages': messages,
            'question': semantic['question'],
        })
        advice_text = self._advice_from_response(response)
        advice_record = {
            'id': secrets.token_hex(16),
            'question': semantic['question'],
            'text': advice_text,
            'context_revision': context_revision,
        }

        with self.transaction() as db:
            current = self.owned(db, 'conversations', owner, semantic['conversation_id'])
            replay = self._replay(db, owner, request_id, 'coach', semantic)
            if replay is not None:
                return replay
            advice = json.loads(current['advice'])
            advice.append(advice_record)
            db.execute(
                'UPDATE conversations SET advice=? WHERE id=? AND owner=?',
                (encode(advice), current['id'], owner))
            result = {'advice': advice_record}
            self._save_replay(db, owner, request_id, 'coach', semantic, result)
            return result

    def _workflow_rank(self, owner, request_id, semantic):
        requested = semantic['asset_ids']
        with self.transaction() as db:
            assets = [self.owned(db, 'assets', owner, asset_id) for asset_id in requested]
            if any(asset['kind'] != 'photo' for asset in assets):
                invalid()
            replay = self._replay(db, owner, request_id, 'rank', semantic)
            if replay is not None:
                return replay
            profile = self.profile(db, owner)
            profile_context = {'tone': profile['tone'], 'goal': profile['goal']}
            filenames = [asset['filename'] for asset in assets]

        # Read and validate every canonical file before making one provider
        # request.  A bad member invalidates the entire operation.
        images = []
        try:
            for asset_id, filename in zip(requested, filenames):
                raw = media.read_asset(self.uploads, filename)
                images.append({
                    'asset_id': asset_id,
                    'mime_type': 'image/png',
                    'image_base64': base64.b64encode(raw).decode('ascii'),
                })
        except Exception as error:
            raise Failure(502, 'provider_failed') from error

        response = self._call_provider('/photo-scores', {
            'preferences': profile_context,
            'images': images,
        })
        items = self._scores_from_response(response, requested)

        with self.transaction() as db:
            # There are no public asset deletes, but re-check ownership before
            # committing so the result can never be attached to another user.
            for asset_id in requested:
                asset = self.owned(db, 'assets', owner, asset_id)
                if asset['kind'] != 'photo':
                    invalid()
            replay = self._replay(db, owner, request_id, 'rank', semantic)
            if replay is not None:
                return replay
            ranking = {'id': secrets.token_hex(16), 'items': items}
            db.execute(
                'INSERT INTO rankings VALUES (?,?,?)',
                (ranking['id'], owner, encode(items)))
            result = {'ranking': ranking}
            self._save_replay(db, owner, request_id, 'rank', semantic, result)
            return result


__all__ = ['Failure', 'Store']
