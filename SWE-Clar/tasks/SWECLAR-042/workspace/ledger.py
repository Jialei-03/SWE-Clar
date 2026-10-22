"""Existing atomic SQLite adapter; the candidate implements the domain transition."""
import json
import sqlite3
from solution import process_review_action


def apply_action(database, seed, action):
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS workflow (singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT state FROM workflow WHERE singleton=1').fetchone()
        state = json.loads(row[0]) if row else seed
        result = process_review_action(state, action)
        if not isinstance(result, dict):
            raise TypeError('Transition must return a JSON object')
        if 'error' not in result:
            connection.execute('INSERT INTO workflow VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET state=excluded.state',
                               (json.dumps(result, allow_nan=False),))
        return result
