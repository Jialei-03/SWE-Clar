"""Persistent storage for the independent local network demo."""
import hashlib
import json
import sqlite3


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def password_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def initialize(path, fixtures):
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, display TEXT NOT NULL,
          role TEXT NOT NULL, password_hash TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
          interests TEXT NOT NULL, plan TEXT NOT NULL DEFAULT 'free');
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS connections(a TEXT, b TEXT, requester TEXT, accepted INTEGER,
          PRIMARY KEY(a,b));
        CREATE TABLE IF NOT EXISTS blocks(actor TEXT, target TEXT, PRIMARY KEY(actor,target));
        CREATE TABLE IF NOT EXISTS groups(id TEXT PRIMARY KEY, owner TEXT, name TEXT);
        CREATE TABLE IF NOT EXISTS members(group_id TEXT, user_id TEXT, PRIMARY KEY(group_id,user_id));
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, sender TEXT, recipient TEXT, content TEXT);
        CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY, group_id TEXT, author TEXT, content TEXT, featured INTEGER);
        CREATE TABLE IF NOT EXISTS likes(post_id TEXT, user_id TEXT, PRIMARY KEY(post_id,user_id));
        CREATE TABLE IF NOT EXISTS payments(receipt_id TEXT PRIMARY KEY, user_id TEXT, plan TEXT);
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT);
        ''')
        if not db.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone():
            for u in fixtures['accounts']:
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',
                    (u['id'],u['display'],u['role'],password_hash(u['password']),u['x'],u['y'],json.dumps(u['interests']),'free'))
            for a,b in fixtures.get('connections',[]):
                a,b=sorted([a,b])
                db.execute('INSERT INTO connections VALUES(?,?,?,1)',(a,b,a))
            db.execute("INSERT INTO metadata VALUES('seeded','yes')")


def public_user(row):
    return {k:json.loads(row[k]) if k=='interests' else row[k]
            for k in ('id','display','role','x','y','interests','plan')}
