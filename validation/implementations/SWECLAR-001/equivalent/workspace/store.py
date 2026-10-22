"""SQLite persistence, access control and transactional workspace state."""
import json
import sqlite3
from uuid import uuid4

from domain import AppError, may_create, may_read, may_write, validate_fields, integer


class Store:
    """The application data store.

    Every operation opens its own SQLite connection.  Writes use an immediate
    transaction so offer callbacks, polling and user edits cannot observe or
    commit a half-applied operation.
    """

    LISTING_FIELDS = (
        'id',
        'owner_id',
        'agent_id',
        'label',
        'property_type',
        'bedrooms',
        'bathrooms',
        'floor_area',
        'asking_price',
        'features',
        'state',
    )

    OFFER_FIELDS = (
        'external_id',
        'listing_id',
        'revision',
        'amount',
        'terms',
    )

    def __init__(self, path, seed):
        self.path = path
        with self.connect() as db:
            db.executescript(
                '''
                CREATE TABLE IF NOT EXISTS users(
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS listings(
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offers(
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notices(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT,
                    actor TEXT,
                    offer_id TEXT,
                    revision INTEGER,
                    listing_id TEXT,
                    data TEXT,
                    UNIQUE(kind, actor, offer_id, revision)
                );
                CREATE TABLE IF NOT EXISTS metadata(
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                '''
            )
            # The marker and all seed rows are committed together.  A second
            # process opening the same fresh database waits for this lock and
            # then observes the marker instead of seeding twice.
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone() is None:
                users = seed.get('users', []) if isinstance(seed, dict) else []
                listings = seed.get('listings', []) if isinstance(seed, dict) else []
                db.executemany(
                    'INSERT INTO users(id, data) VALUES(?, ?)',
                    [(row['id'], json.dumps(row)) for row in users],
                )
                db.executemany(
                    'INSERT INTO listings(id, data) VALUES(?, ?)',
                    [(row['id'], json.dumps(row)) for row in listings],
                )
                self.set_meta(db, 'seeded', True)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        return db

    @staticmethod
    def set_meta(db, key, value):
        db.execute(
            'INSERT INTO metadata(key, data) VALUES(?, ?) '
            'ON CONFLICT(key) DO UPDATE SET data=excluded.data',
            (key, json.dumps(value)),
        )

    @staticmethod
    def meta(db, key, default=None):
        row = db.execute('SELECT data FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row['data']) if row else default

    @staticmethod
    def row(db, table, key):
        row = db.execute(f'SELECT data FROM {table} WHERE id=?', (key,)).fetchone()
        return json.loads(row['data']) if row else None

    @classmethod
    def listing_view(cls, listing):
        """Return the public listing shape, excluding seed/source extras."""
        return {key: listing.get(key) for key in cls.LISTING_FIELDS}

    @classmethod
    def offer_view(cls, offer):
        """Return the public current-offer shape.

        The provider cursor is an integration checkpoint rather than an offer
        field, so it remains internal to synchronization state.
        """
        return {key: offer.get(key) for key in cls.OFFER_FIELDS}

    @classmethod
    def actor_view(cls, actor):
        result = {'id': actor.get('id'), 'role': actor.get('role')}
        if 'agent_id' in actor:
            result['agent_id'] = actor.get('agent_id')
        return result

    def actors(self):
        with self.connect() as db:
            rows = [
                json.loads(row['data'])
                for row in db.execute('SELECT data FROM users ORDER BY id')
            ]
        return [self.actor_view(row) for row in rows]

    def actor(self, key):
        with self.connect() as db:
            actor = self.row(db, 'users', key)
        if actor is None or actor.get('role') not in ['seller', 'agent', 'admin']:
            raise AppError(401, {'actor': 'unknown identity'})
        return actor

    def listings(self, actor):
        with self.connect() as db:
            rows = [
                json.loads(row['data'])
                for row in db.execute('SELECT data FROM listings ORDER BY id')
            ]
        return [self.listing_view(row) for row in rows if may_read(actor, row)]

    def get(self, actor, key):
        with self.connect() as db:
            listing = self.row(db, 'listings', key)
            if listing is None or not may_read(actor, listing):
                raise AppError(404, {'listing': 'not found'})
            offers = [
                json.loads(row['data'])
                for row in db.execute('SELECT data FROM offers ORDER BY id')
            ]
            notices = [
                dict(row)
                for row in db.execute(
                    'SELECT sequence, kind, actor, offer_id, revision, listing_id, data '
                    'FROM notices WHERE listing_id=? ORDER BY sequence',
                    (key,),
                )
            ]
        return {
            'listing': self.listing_view(listing),
            'offers': [self.offer_view(row) for row in offers if row.get('listing_id') == key],
            'notifications': [
                {**row, 'data': json.loads(row['data'])} for row in notices
            ],
        }

    def _new_listing_id(self, db):
        # UUID collisions are fantastically unlikely, but checking under the
        # write lock makes uniqueness an actual invariant rather than an
        # assumption.
        while True:
            key = 'parcel-' + uuid4().hex[:12]
            if db.execute('SELECT 1 FROM listings WHERE id=?', (key,)).fetchone() is None:
                return key

    def save(self, actor, body, key=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = self.row(db, 'listings', key) if key is not None else None
            if key is not None:
                if old is None or not may_read(actor, old):
                    # A record outside the caller's scope is deliberately
                    # indistinguishable from an unavailable record.
                    raise AppError(404, {'listing': 'not found'})
                if not may_write(actor, old):
                    raise AppError(403, {'listing': 'read only'})
            elif not may_create(actor):
                raise AppError(403, {'listing': 'read only'})

            values = validate_fields(body, old)
            if old is None:
                listing_id = self._new_listing_id(db)
                owner_id = actor['id']
                agent_id = actor.get('agent_id')
            else:
                listing_id = old['id']
                owner_id = old.get('owner_id')
                agent_id = old.get('agent_id')

            record = {
                'id': listing_id,
                'owner_id': owner_id,
                'agent_id': agent_id,
                **values,
                # There is intentionally no publication operation.
                'state': 'draft',
            }
            if old is None:
                db.execute(
                    'INSERT INTO listings(id, data) VALUES(?, ?)',
                    (record['id'], json.dumps(record)),
                )
            else:
                db.execute(
                    'UPDATE listings SET data=? WHERE id=?',
                    (json.dumps(record), record['id']),
                )
        return self.listing_view(record)

    def integration_state(self):
        with self.connect() as db:
            mode = self.meta(db, 'provider_mode', None)
            cursor = self.meta(db, 'provider_cursor', 0)
            last_poll = self.meta(db, 'provider_last_poll', None)
            callback_url = self.meta(db, 'provider_callback_url', None)
        return {
            'mode': mode,
            'cursor': cursor,
            'last_poll': last_poll,
            'callback_url': callback_url,
        }

    def set_webhook(self, callback_url):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.set_meta(db, 'provider_mode', 'webhook')
            self.set_meta(db, 'provider_callback_url', callback_url)

    @staticmethod
    def _event_error(message='invalid offer event batch'):
        raise AppError(400, {'events': message})

    @staticmethod
    def _insert_notice(db, kind, actor, offer_id, revision, listing_id, data):
        """Insert an idempotent notice without consuming a sequence gap."""
        exists = db.execute(
            'SELECT 1 FROM notices WHERE kind=? AND actor=? AND offer_id=? AND revision=?',
            (kind, actor, offer_id, revision),
        ).fetchone()
        if exists is not None:
            return False
        db.execute(
            'INSERT INTO notices(kind, actor, offer_id, revision, listing_id, data) '
            'VALUES(?, ?, ?, ?, ?, ?)',
            (kind, actor, offer_id, revision, listing_id, json.dumps(data)),
        )
        return True

    def _validated_events(self, db, events):
        """Validate every event and its listing/external-ID relationships.

        This is intentionally completed before any INSERT or UPDATE.  The
        caller can therefore safely use the resulting list in one transaction.
        """
        if not isinstance(events, list):
            self._event_error('list required')

        prepared = []
        seen_listing = {}
        existing_cache = {}
        for event in events:
            if not isinstance(event, dict):
                self._event_error()

            external_id = event.get('external_id')
            listing_id = event.get('listing_id')
            terms = event.get('terms')
            if (
                not isinstance(external_id, str)
                or not external_id
                or len(external_id) > 64
            ):
                self._event_error()
            if (
                not isinstance(listing_id, str)
                or not listing_id
                or len(listing_id) > 64
            ):
                self._event_error()
            if not integer(event.get('cursor'), 1, 10 ** 12):
                self._event_error()
            if not integer(event.get('revision'), 1, 10 ** 9):
                self._event_error()
            if not integer(event.get('amount'), 1, 10 ** 12):
                self._event_error()
            if not isinstance(terms, str) or not terms or len(terms) > 2000:
                self._event_error()

            listing = self.row(db, 'listings', listing_id)
            if listing is None:
                self._event_error('unknown listing')

            previous_listing = seen_listing.get(external_id)
            if previous_listing is not None and previous_listing != listing_id:
                self._event_error('external offer belongs to another listing')
            seen_listing[external_id] = listing_id

            if external_id not in existing_cache:
                existing_cache[external_id] = self.row(db, 'offers', external_id)
            existing = existing_cache[external_id]
            if existing is not None and existing.get('listing_id') != listing_id:
                self._event_error('external offer belongs to another listing')

            prepared.append(
                {
                    'cursor': event['cursor'],
                    'external_id': external_id,
                    'listing_id': listing_id,
                    'revision': event['revision'],
                    'amount': event['amount'],
                    'terms': terms,
                }
            )
        return prepared

    def _apply_events_in_transaction(self, db, events):
        prepared = self._validated_events(db, events)
        updated = 0
        for event in prepared:
            current = self.row(db, 'offers', event['external_id'])
            if current is not None and event['revision'] <= current['revision']:
                # Repeated and older revisions are deliberately no-ops,
                # including amount/terms changes at the same revision.
                continue

            new_offer = {
                'cursor': event['cursor'],
                'external_id': event['external_id'],
                'listing_id': event['listing_id'],
                'revision': event['revision'],
                'amount': event['amount'],
                'terms': event['terms'],
            }
            if current is None:
                db.execute(
                    'INSERT INTO offers(id, data) VALUES(?, ?)',
                    (event['external_id'], json.dumps(new_offer)),
                )
            else:
                db.execute(
                    'UPDATE offers SET data=? WHERE id=?',
                    (json.dumps(new_offer), event['external_id']),
                )

            listing = self.row(db, 'listings', event['listing_id'])
            notice_data = {'amount': event['amount'], 'terms': event['terms']}
            self._insert_notice(
                db,
                'offer_update',
                listing.get('owner_id'),
                event['external_id'],
                event['revision'],
                event['listing_id'],
                notice_data,
            )
            updated += 1
        return updated

    def receive_events(self, events):
        """Apply a validated callback batch and return advancing revisions."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            updated = self._apply_events_in_transaction(db, events)
            if events:
                highest = max(event['cursor'] for event in events)
                current_cursor = self.meta(db, 'provider_cursor', 0)
                if not integer(current_cursor, 0, 10 ** 12):
                    current_cursor = 0
                if highest > current_cursor:
                    self.set_meta(db, 'provider_cursor', highest)
        return updated

    def commit_poll(self, events, cursor, now):
        """Apply a complete poll response and its checkpoint atomically."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current_cursor = self.meta(db, 'provider_cursor', 0)
            if not integer(current_cursor, 0, 10 ** 12) or cursor < current_cursor:
                raise AppError(400, {'provider': 'cursor moved backwards'})
            updated = self._apply_events_in_transaction(db, events)
            self.set_meta(db, 'provider_mode', 'poll')
            self.set_meta(db, 'provider_cursor', cursor)
            self.set_meta(db, 'provider_last_poll', now)
        return updated

    def review(self, actor, key, service_url):
        from urllib.parse import quote

        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            offer = self.row(db, 'offers', key)
            if offer is None:
                raise AppError(404, {'offer': 'not found'})
            listing = self.row(db, 'listings', offer.get('listing_id'))
            if listing is None or not may_read(actor, listing):
                raise AppError(404, {'offer': 'not found'})

            self._insert_notice(
                db,
                'offer_review',
                actor['id'],
                offer['external_id'],
                offer['revision'],
                offer['listing_id'],
                {
                    'amount': offer['amount'],
                    'terms': offer['terms'],
                },
            )
        return service_url.rstrip('/') + '/review/' + quote(key, safe='')
