"""SQLite-backed synthetic listing workspace. No customer data is included."""
import json
import sqlite3
from uuid import uuid4
from domain import AppError, may_read, may_write, validate_fields


class Store:
    def __init__(self, path, seed):
        self.path = path
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS listings(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS offers(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notices(sequence INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, actor TEXT, offer_id TEXT, revision INTEGER, listing_id TEXT, data TEXT, UNIQUE(kind,actor,offer_id,revision));
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, data TEXT NOT NULL);''')
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone() is None:
                for table in ['users', 'listings']:
                    db.executemany(f'INSERT INTO {table} VALUES(?,?)', [(row['id'], json.dumps(row)) for row in seed[table]])
                self.set_meta(db, 'seeded', True)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def set_meta(db, key, value):
        db.execute('INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data', (key, json.dumps(value)))

    @staticmethod
    def meta(db, key, default=None):
        row = db.execute('SELECT data FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row['data']) if row else default

    @staticmethod
    def row(db, table, key):
        row = db.execute(f'SELECT data FROM {table} WHERE id=?', (key,)).fetchone()
        return json.loads(row['data']) if row else None

    def actors(self):
        with self.connect() as db:
            return [json.loads(row['data']) for row in db.execute('SELECT data FROM users ORDER BY id')]

    def actor(self, key):
        with self.connect() as db:
            actor = self.row(db, 'users', key)
        if actor is None or actor['role'] not in ['seller', 'agent', 'admin']:
            raise AppError(401, {'actor': 'unknown identity'})
        return actor

    def listings(self, actor):
        with self.connect() as db:
            rows = [json.loads(row['data']) for row in db.execute('SELECT data FROM listings ORDER BY id')]
        return [row for row in rows if may_read(actor, row)]

    def get(self, actor, key):
        with self.connect() as db:
            listing = self.row(db, 'listings', key)
            if listing is None or not may_read(actor, listing):
                raise AppError(404, {'listing': 'not found'})
            offers = [json.loads(r['data']) for r in db.execute('SELECT data FROM offers ORDER BY id')]
            notices = [dict(r) for r in db.execute('SELECT * FROM notices WHERE listing_id=? ORDER BY sequence', (key,))]
        return {'listing': listing, 'offers': [r for r in offers if r['listing_id'] == key], 'notifications': [{**r, 'data': json.loads(r['data'])} for r in notices]}

    def save(self, actor, body, key=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = self.row(db, 'listings', key) if key else None
            if key:
                if old is None or not may_read(actor, old):
                    raise AppError(404, {'listing': 'not found'})
                if not may_write(actor, old):
                    raise AppError(403, {'listing': 'read only'})
            values = validate_fields(body, old)
            record = {**(old or {'id': 'parcel-' + uuid4().hex[:12], 'owner_id': actor['id'], 'agent_id': actor.get('agent_id')}), **values, 'state': 'draft'}
            db.execute('INSERT INTO listings VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (record['id'], json.dumps(record)))
        return record

    def review(self, actor, key, service_url):
        raise AppError(501, {'review': 'offer review workflow is unfinished'})
