"""Transactional storage for the small benchmark policy service."""
import json
import sqlite3
from pathlib import Path
from policy import process_control_action


class Store:
    def __init__(self, path):
        self.path = str(path)

    def initialize(self, seed):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO snapshot VALUES (1, ?)', (json.dumps(seed),))

    def read(self):
        with sqlite3.connect(self.path) as db:
            return json.loads(db.execute('SELECT body FROM snapshot WHERE id=1').fetchone()[0])

    def apply(self, action):
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            state = json.loads(db.execute('SELECT body FROM snapshot WHERE id=1').fetchone()[0])
            result = process_control_action(state, action)
            # Errors are responses, not committed mutations.
            if 'error' not in result:
                saved = {k: v for k, v in result.items() if k != 'result'}
                db.execute('UPDATE snapshot SET body=? WHERE id=1', (json.dumps(saved, allow_nan=False),))
            return result
