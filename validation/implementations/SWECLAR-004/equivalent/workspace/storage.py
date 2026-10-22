"""Persistent storage for the independent local network demo."""
import hashlib
import json
import sqlite3
import uuid


def connect(path):
    """Open one short-lived application connection.

    A connection is deliberately opened per HTTP request.  SQLite's busy
    timeout makes concurrent requests wait for the writer holding the lock,
    while the request handler uses an immediate transaction for mutations.
    """
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    return db


def password_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def initialize(path, fixtures):
    """Create the schema and seed a database exactly once.

    The fixture file is an input to a new database, not a source of data to
    merge on every restart.  Consequently profiles, sessions, relationships,
    posts, messages, likes and membership redemptions all survive a restart.
    """
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(
          id TEXT PRIMARY KEY,
          display TEXT NOT NULL,
          role TEXT NOT NULL,
          password_hash TEXT NOT NULL,
          x REAL NOT NULL,
          y REAL NOT NULL,
          interests TEXT NOT NULL,
          plan TEXT NOT NULL DEFAULT 'free'
        );
        CREATE TABLE IF NOT EXISTS sessions(
          token TEXT PRIMARY KEY,
          user_id TEXT REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS connections(
          a TEXT NOT NULL,
          b TEXT NOT NULL,
          requester TEXT NOT NULL,
          accepted INTEGER NOT NULL,
          PRIMARY KEY(a,b)
        );
        CREATE TABLE IF NOT EXISTS blocks(
          actor TEXT NOT NULL,
          target TEXT NOT NULL,
          PRIMARY KEY(actor,target)
        );
        CREATE TABLE IF NOT EXISTS groups(
          id TEXT PRIMARY KEY,
          owner TEXT NOT NULL,
          name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS members(
          group_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          PRIMARY KEY(group_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS messages(
          id TEXT PRIMARY KEY,
          sender TEXT NOT NULL,
          recipient TEXT NOT NULL,
          content TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS posts(
          id TEXT PRIMARY KEY,
          group_id TEXT NOT NULL,
          author TEXT NOT NULL,
          content TEXT NOT NULL,
          featured INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS likes(
          post_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          PRIMARY KEY(post_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS payments(
          receipt_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          plan TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS metadata(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS connections_a_idx ON connections(a);
        CREATE INDEX IF NOT EXISTS connections_b_idx ON connections(b);
        CREATE INDEX IF NOT EXISTS messages_sender_idx ON messages(sender);
        CREATE INDEX IF NOT EXISTS messages_recipient_idx ON messages(recipient);
        CREATE INDEX IF NOT EXISTS posts_group_idx ON posts(group_id);
        CREATE INDEX IF NOT EXISTS blocks_target_idx ON blocks(target);
        ''')

        seeded = db.execute(
            "SELECT 1 FROM metadata WHERE key='seeded'"
        ).fetchone()
        if seeded is None:
            # A database containing users is already an existing application
            # database even if it predates the marker.  This avoids merging a
            # newly supplied fixture into user-created state.
            has_users = db.execute('SELECT 1 FROM users LIMIT 1').fetchone()
            if has_users is None:
                for account in fixtures.get('accounts', []):
                    db.execute(
                        '''INSERT INTO users
                           (id,display,role,password_hash,x,y,interests,plan)
                           VALUES(?,?,?,?,?,?,?,?)''',
                        (
                            account['id'],
                            account['display'],
                            account['role'],
                            password_hash(account['password']),
                            account['x'],
                            account['y'],
                            json.dumps(account['interests'], ensure_ascii=False),
                            'free',
                        ),
                    )
                for pair in fixtures.get('connections', []):
                    # Fixture connections are accepted and undirected.  Store
                    # one canonical row, as all later connection operations do.
                    left, right = sorted((pair[0], pair[1]))
                    db.execute(
                        '''INSERT OR IGNORE INTO connections
                           (a,b,requester,accepted) VALUES(?,?,?,1)''',
                        (left, right, left),
                    )
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('seeded','yes')")


def fresh_id(db, table):
    """Return an unused opaque identifier for one of the activity tables.

    UUID collisions are extraordinarily unlikely, but checking the table makes
    the uniqueness guarantee explicit rather than making it probabilistic.
    The table names are intentionally allow-listed because they are inserted
    into a SQL identifier position rather than passed as values.
    """
    if table not in {'groups', 'messages', 'posts'}:
        raise ValueError('unsupported activity table')
    while True:
        ident = uuid.uuid4().hex
        if db.execute(
            f'SELECT 1 FROM {table} WHERE id=?', (ident,)
        ).fetchone() is None:
            return ident


def public_user(row):
    """Return only the public account fields promised by the HTTP contract."""
    # Keep this allow-list explicit: a database row also contains the
    # password hash, and the public projection must never grow by accident if
    # the users table gains another private column.
    return {
        'id': row['id'],
        'display': row['display'],
        'role': row['role'],
        'x': row['x'],
        'y': row['y'],
        'interests': json.loads(row['interests']),
        'plan': row['plan'],
    }
