"""Real independent SQLite persistence and fixture initialization."""
from contextlib import contextmanager
import hashlib
import json
import secrets
import sqlite3
from common import canonical_url


def connect(path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise


def password_digest(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt+'$'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),120000).hex()


def initialize(path, fixture_path, provider):
    db=connect(path)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,name TEXT NOT NULL,password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id));
        CREATE TABLE IF NOT EXISTS competitors(account_id TEXT NOT NULL,competitor_id TEXT NOT NULL,name TEXT NOT NULL,archived INTEGER NOT NULL,epoch INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(account_id,competitor_id));
        CREATE TABLE IF NOT EXISTS urls(account_id TEXT NOT NULL,url_id TEXT NOT NULL,competitor_id TEXT NOT NULL,ordinal INTEGER NOT NULL,url TEXT NOT NULL,text TEXT,sha256 TEXT,observed_at_ms INTEGER,PRIMARY KEY(account_id,url_id),FOREIGN KEY(account_id,competitor_id) REFERENCES competitors(account_id,competitor_id));
        CREATE TABLE IF NOT EXISTS snapshots(account_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,url_id TEXT NOT NULL,observed_at_ms INTEGER NOT NULL,text TEXT NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(account_id,snapshot_id));
        CREATE TABLE IF NOT EXISTS events(account_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,url_id TEXT NOT NULL,observed_at_ms INTEGER NOT NULL,before_text TEXT NOT NULL,after_text TEXT NOT NULL,before_sha256 TEXT NOT NULL,after_sha256 TEXT NOT NULL,PRIMARY KEY(account_id,snapshot_id));
        CREATE TABLE IF NOT EXISTS subscriptions(account_id TEXT PRIMARY KEY,sequence INTEGER NOT NULL,plan TEXT NOT NULL,status TEXT NOT NULL,revocation_epoch INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS receipts(account_id TEXT NOT NULL,id TEXT NOT NULL,sequence INTEGER NOT NULL,plan TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(account_id,id),UNIQUE(account_id,sequence));
        ''')
        # The starter schema already includes these internal lifecycle
        # counters.  Keep a database created by an older foundation build
        # runnable as well; required public columns are never renamed.
        for table, column, definition in [
            ('competitors', 'epoch', 'INTEGER NOT NULL DEFAULT 0'),
            ('subscriptions', 'revocation_epoch', 'INTEGER NOT NULL DEFAULT 0'),
        ]:
            columns = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
            if column not in columns:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        with transaction(db):
            if db.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone():
                return
            fixture=json.loads(fixture_path.read_text())
            for account in fixture['accounts']:
                db.execute('INSERT INTO accounts VALUES(?,?,?)',(account['id'],account['name'],password_digest(account['password'])))
                db.execute('INSERT INTO subscriptions(account_id,sequence,plan,status) VALUES(?,0,?,?)',(account['id'],'basic','cancelled'))
            for sub in fixture.get('subscriptions',[]):
                db.execute('UPDATE subscriptions SET sequence=?,plan=?,status=? WHERE account_id=?',(sub['sequence'],sub['plan'],sub['status'],sub['account_id']))
            for competitor in fixture.get('competitors',[]):
                account_id, key = competitor['account_id'], competitor['competitor_id']
                db.execute('INSERT INTO competitors(account_id,competitor_id,name,archived) VALUES(?,?,?,?)',(account_id,key,competitor['name'],int(competitor['archived'])))
                for order, url in enumerate(competitor['urls']):
                    if url.startswith('/pages/'):
                        url=provider+url
                    db.execute('INSERT INTO urls(account_id,url_id,competitor_id,ordinal,url) VALUES(?,?,?,?,?)',(account_id,secrets.token_hex(12),key,order,canonical_url(url,provider)))
            db.execute("INSERT INTO meta VALUES('initialized','1')")
    finally:
        db.close()
