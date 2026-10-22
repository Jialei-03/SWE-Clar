"""Synthetic loyalty domain with serialized, durable SQLite transactions."""
import datetime
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
from pathlib import Path
from urllib.parse import quote, unquote

from media import sanitize


class Fault(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def fail(status=400, code='invalid_request'):
    raise Fault(status, code)


def string(value, maximum=100, trim=False):
    if not isinstance(value, str) or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        fail()
    if trim:
        value = value.strip()
    if not 1 <= len(value) <= maximum:
        fail()
    return value


def integer(value, maximum=2000000000):
    if type(value) is not int or not 0 <= value <= maximum:
        fail()
    return value


def boolean(value):
    if type(value) is not bool:
        fail()
    return value


def choices(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        fail()
    return value


def identifiers(value, minimum=0, maximum=None):
    if not isinstance(value, list) or len(value) < minimum or (maximum is not None and len(value) > maximum):
        fail()
    result = [string(item) for item in value]
    if len(set(result)) != len(result):
        fail()
    return result


def uid():
    return secrets.token_hex(20)


def public_user(user):
    return {key: user[key] for key in ('id', 'username', 'role')}


class Store:
    def __init__(self, database, fixture, clock):
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, check_same_thread=False, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
        self.lock = threading.RLock()
        self.sessions = {}
        self.clock = Path(clock)
        if not self.db.execute('SELECT 1 FROM state').fetchone():
            state = json.loads(Path(fixture).read_text())
            for user in state['users']:
                salt = secrets.token_hex(16)
                password = user.pop('password')
                user['salt'] = salt
                user['digest'] = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120000).hex()
            for name in ('assets', 'receipts', 'promotions', 'messages', 'ledger', 'redemptions'):
                state[name] = []
            state['preferences'] = {}
            self.db.execute('INSERT INTO state VALUES(1,?)', (json.dumps(state, ensure_ascii=True),))

    def authorize(self, method, path, token):
        """Check identity and endpoint role before HTTP payload syntax."""
        if (method, path) in (('GET', '/health'), ('POST', '/api/login')):
            return
        with self.lock:
            state = json.loads(self.db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
            owner = self.sessions.get(token)
            user = next((u for u in state['users'] if u['id'] == owner and u['active']), None)
            if user is None:
                fail(401, 'unauthenticated')
            roles = None
            if path == '/api/merchant-owners' or method == 'POST' and path in ('/api/malls', '/api/shops', '/api/branches', '/api/dispatch') or method == 'PATCH' and re.fullmatch(r'/api/branches/[^/]+', path) or method == 'POST' and re.fullmatch(r'/api/receipts/[^/]+/review', path):
                roles = ('administrator',)
            elif path in ('/api/preferences', '/api/inbox', '/api/wallet', '/api/assets') or method == 'POST' and path in ('/api/receipts', '/api/redemptions'):
                roles = ('consumer',)
            elif method == 'POST' and (path == '/api/promotions' or re.fullmatch(r'/api/promotions/[^/]+/cancel', path)):
                roles = ('merchant',)
            elif method == 'GET' and path in ('/api/receipts', '/api/redemptions'):
                roles = ('consumer', 'administrator')
            elif method == 'GET' and path == '/api/promotions':
                roles = ('merchant', 'administrator')
            if roles:
                self.role(user, *roles)

    def handle(self, method, path, token, body=None):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.s = json.loads(self.db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
                answer = self.route(method, path, token, body or {})
                self.db.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(self.s, ensure_ascii=True),))
                self.db.execute('COMMIT')
                return answer
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def lookup(self, collection, identity):
        return next((row for row in self.s[collection] if row['id'] == identity), None)

    def need(self, collection, identity):
        row = self.lookup(collection, identity)
        if row is None:
            fail(404, 'not_found')
        return row

    def role(self, user, *roles):
        if user['role'] not in roles:
            fail(403, 'forbidden')

    def asset(self, row):
        return {key: row[key] for key in ('id', 'width', 'height', 'url')}

    def balance(self, owner):
        return sum(row['delta'] for row in self.s['ledger'] if row['owner_id'] == owner)

    def route(self, method, path, token, b):
        if method == 'GET' and path == '/health':
            return 200, {'ok': True}
        if method == 'POST' and path == '/api/login':
            username = string(b.get('username'))
            password = string(b.get('password'), 10000)
            user = next((u for u in self.s['users'] if u['username'] == username), None)
            if not user or not user['active'] or not hmac.compare_digest(user['digest'], hashlib.pbkdf2_hmac(
                    'sha256', password.encode(), user['salt'].encode(), 120000).hex()):
                fail(401, 'unauthenticated')
            session = secrets.token_urlsafe(32)
            self.sessions[session] = user['id']
            return 200, {'token': session, 'user': public_user(user)}
        user = self.lookup('users', self.sessions.get(token))
        if user is None or not user['active']:
            fail(401, 'unauthenticated')
        owner = user['id']
        if method == 'GET' and path == '/api/me':
            return 200, {'user': public_user(user)}
        if method == 'POST' and path == '/api/logout':
            self.sessions.pop(token, None)
            return 200, {'ok': True}
        if method == 'GET' and path == '/api/merchant-owners':
            self.role(user, 'administrator')
            return 200, {'merchant_owners': [{'id': u['id']} for u in self.s['users'] if u['role'] == 'merchant' and u['active']]}
        if method == 'GET' and path == '/api/catalog':
            return 200, {key: self.s[key] for key in ('malls', 'shops', 'branches', 'rewards')}
        if method == 'POST' and path in ('/api/malls', '/api/shops', '/api/branches'):
            self.role(user, 'administrator')
            collection = path.split('/')[-1]
            row = {'id': string(b.get('id'))}
            if collection in ('malls', 'shops'):
                row['name'] = string(b.get('name'), trim=True)
            if collection == 'shops':
                row.update(owner_id=string(b.get('owner_id')), category=choices(b.get('category'), ('food', 'home', 'leisure')))
            if collection == 'branches':
                row.update(shop_id=string(b.get('shop_id')), mall_id=string(b.get('mall_id')), participating=boolean(b.get('participating')))
            if self.lookup(collection, row['id']):
                fail(409, 'duplicate_id')
            if collection == 'shops':
                merchant = self.need('users', row['owner_id'])
                if merchant['role'] != 'merchant' or not merchant['active']:
                    fail(422, 'invalid_owner')
            if collection == 'branches':
                self.need('shops', row['shop_id'])
                self.need('malls', row['mall_id'])
            self.s[collection].append(row)
            return 201, {{'malls': 'mall', 'shops': 'shop', 'branches': 'branch'}[collection]: row}
        match = re.fullmatch(r'/api/branches/([^/]+)', path)
        if match and method == 'PATCH':
            self.role(user, 'administrator')
            value = boolean(b.get('participating'))
            row = self.need('branches', string(unquote(match[1])))
            row['participating'] = value
            return 200, {'branch': row}
        if path == '/api/assets' and method in ('GET', 'POST'):
            self.role(user, 'consumer')
            if method == 'GET':
                return 200, {'assets': [self.asset(a) for a in self.s['assets'] if a['owner_id'] == owner]}
            import base64
            try:
                raw, width, height = sanitize(b.get('png_base64'))
            except Exception:
                fail()
            identity = uid()
            row = dict(id=identity, owner_id=owner, width=width, height=height,
                       url='/api/assets/' + quote(identity, safe=''), png=base64.b64encode(raw).decode())
            self.s['assets'].append(row)
            return 201, {'asset': self.asset(row)}
        match = re.fullmatch(r'/api/assets/([^/]+)', path)
        if match and method == 'GET':
            import base64
            row = self.need('assets', string(unquote(match[1])))
            attached = any(r['asset_id'] == row['id'] for r in self.s['receipts'])
            if not (user['role'] == 'consumer' and row['owner_id'] == owner or user['role'] == 'administrator' and attached):
                fail(404, 'not_found')
            return 200, base64.b64decode(row['png'])
        if path == '/api/receipts' and method == 'POST':
            self.role(user, 'consumer')
            fields = {key: string(b.get(key)) for key in ('request_id', 'branch_id', 'asset_id')}
            fields['receipt_number'] = string(b.get('receipt_number'), trim=True)
            fields['date'] = string(b.get('date'))
            fields['amount_cents'] = integer(b.get('amount_cents'), 100000000)
            try:
                if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', fields['date']):
                    fail()
                datetime.date.fromisoformat(fields['date'])
            except ValueError:
                fail()
            asset = self.need('assets', fields['asset_id'])
            if asset['owner_id'] != owner:
                fail(404, 'not_found')
            branch = self.need('branches', fields['branch_id'])
            if not branch['participating']:
                fail(422, 'not_participating')
            row = dict(fields, id=uid(), owner_id=owner, status='pending', points=0, reviewed_by=None)
            self.s['receipts'].append(row)
            return 201, {'receipt': row}
        if path == '/api/receipts' and method == 'GET':
            self.role(user, 'consumer', 'administrator')
            rows = [r for r in self.s['receipts'] if user['role'] == 'administrator' or r['owner_id'] == owner]
            return 200, {'receipts': sorted(rows, key=lambda r: r['status'] != 'pending')}
        if path == '/api/preferences' and method == 'GET':
            self.role(user, 'consumer')
            return 200, {'preferences': {'categories': [], 'mall_ids': []}}
        if path == '/api/promotions' and method == 'GET':
            self.role(user, 'merchant', 'administrator')
            return 200, {'promotions': []}
        if path == '/api/inbox' and method == 'GET':
            self.role(user, 'consumer')
            return 200, {'messages': [{k: v for k, v in r.items() if k != 'owner_id'} for r in self.s['messages'] if r['owner_id'] == owner]}
        if path == '/api/wallet' and method == 'GET':
            self.role(user, 'consumer')
            return 200, dict(balance=self.balance(owner), ledger=[{k: v for k, v in r.items() if k != 'owner_id'} for r in self.s['ledger'] if r['owner_id'] == owner],
                             redemptions=[r for r in self.s['redemptions'] if r['owner_id'] == owner])
        if path == '/api/redemptions' and method == 'GET':
            self.role(user, 'consumer', 'administrator')
            return 200, {'redemptions': [r for r in self.s['redemptions'] if user['role'] == 'administrator' or r['owner_id'] == owner]}
        fail(404, 'not_found')
