import argparse
import csv
import io
import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY, balance_cents INTEGER NOT NULL,
                    age_days INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                    note TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL, before_status TEXT NOT NULL,
                    after_status TEXT NOT NULL, before_note TEXT NOT NULL,
                    after_note TEXT NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def accounts(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM accounts ORDER BY account_id')]

    def import_csv(self, text):
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames != ['account_id', 'balance_cents', 'age_days']:
            raise ValueError('Expected account_id,balance_cents,age_days columns')
        rows = list(reader)
        if not rows:
            raise ValueError('At least one data row is required')
        seen = set()
        parsed = []
        for row in rows:
            key = row.get('account_id', '')
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', key):
                raise ValueError('Invalid account_id')
            if key in seen or set(row) != {'account_id', 'balance_cents', 'age_days'}:
                raise ValueError('Duplicate ID or malformed row')
            seen.add(key)
            for field in ['balance_cents', 'age_days']:
                if not isinstance(row[field], str) or not re.fullmatch(r'-?\d+', row[field]):
                    raise ValueError('Integer fields required')
            balance, age = int(row['balance_cents']), int(row['age_days'])
            if abs(balance) > 10**12 or not 0 <= age <= 36500:
                raise ValueError('Numeric value outside documented limits')
            parsed.append((key, balance, age))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.executemany('''INSERT INTO accounts(account_id,balance_cents,age_days)
                VALUES(?,?,?) ON CONFLICT(account_id) DO UPDATE SET
                balance_cents=excluded.balance_cents, age_days=excluded.age_days, status='open', note='' 
                ''', parsed)
        return {'imported': len(parsed)}

    def queue(self):
        rows = [r for r in self.accounts() if r['balance_cents'] > 0]
        return sorted(rows, key=lambda r: (-r['age_days'], r['account_id']))

    def follow_up(self, body):
        ids, status, note = body.get('account_ids'), body.get('status'), body.get('note')
        if not isinstance(ids, list) or not ids or any(not isinstance(k, str) for k in ids):
            raise ValueError('Select at least one account')
        if not isinstance(status, str) or not isinstance(note, str):
            raise ValueError('String status and note required')
        changed = 0
        with self.connect() as db:
            for key in ids:
                cursor = db.execute('UPDATE accounts SET status=?,note=? WHERE account_id=?', (status,note,key))
                changed += cursor.rowcount
        return {'updated': changed}

    def history(self, key):
        with self.connect() as db:
            if db.execute('SELECT 1 FROM accounts WHERE account_id=?', (key,)).fetchone() is None:
                raise KeyError(key)
            return [dict(row) for row in db.execute('SELECT * FROM audit WHERE account_id=? ORDER BY sequence', (key,))]

    def export_csv(self):
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['account_id', 'balance_cents', 'age_days', 'status', 'note'])
        for row in self.accounts():
            note = row['note']
            writer.writerow([row[k] for k in ['account_id', 'balance_cents', 'age_days', 'status']] + [note])
        return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, body, content_type='application/json'):
        raw = json.dumps(body).encode() if content_type == 'application/json' else body.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        store = self.server.store
        try:
            if path == '/':
                return self.reply(200, (Path(__file__).parent / 'index.html').read_text(), 'text/html')
            if path == '/health':
                return self.reply(200, {'service': 'receivables'})
            if path == '/api/accounts':
                return self.reply(200, {'accounts': store.accounts()})
            if path == '/api/queue':
                return self.reply(200, {'accounts': store.queue()})
            if path == '/api/export':
                return self.reply(200, store.export_csv(), 'text/csv')
            if path.startswith('/api/accounts/'):
                key = unquote(path[len('/api/accounts/'):])
                account = next((r for r in store.accounts() if r['account_id'] == key), None)
                if account is None:
                    raise KeyError(key)
                return self.reply(200, {'account': account, 'history': store.history(key)})
            self.reply(404, {'error': 'Not found'})
        except KeyError:
            self.reply(404, {'error': 'Unknown account'})

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2_000_000:
                raise ValueError('Invalid request size')
            raw = self.rfile.read(length).decode('utf-8')
            if self.path == '/api/import':
                result = self.server.store.import_csv(raw)
            elif self.path == '/api/follow-ups':
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise ValueError('JSON object required')
                result = self.server.store.follow_up(body)
            else:
                return self.reply(404, {'error': 'Not found'})
            self.reply(200, result)
        except (ValueError, UnicodeError, csv.Error) as error:
            self.reply(400, {'error': str(error)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--db', default='state.sqlite')
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.store = Store(args.db)
    print(json.dumps({'port': server.server_port}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
