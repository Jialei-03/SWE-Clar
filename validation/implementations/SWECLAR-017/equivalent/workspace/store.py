"""Persistent authenticated marketplace with transactional offer decisions."""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import threading


class Failure(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def invalid():
    raise Failure(400, 'invalid_request')


def conflict():
    raise Failure(409, 'conflict')


def forbidden():
    raise Failure(403, 'forbidden')


def integer(value, minimum=0, maximum=None):
    """Validate a JSON integer without accepting JSON booleans."""
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        invalid()
    return value


def cents(value):
    return integer(value, 1, 10000000)


class Store:
    def __init__(self, database, fixture, clock):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.clock = Path(clock)
        self.sessions = {}
        self.lock = threading.RLock()
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS initialized (version INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE, role TEXT, salt TEXT, password TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS listings (id TEXT PRIMARY KEY, seller_id TEXT, title TEXT, price_cents INTEGER, reference_price_cents INTEGER, previous_price_cents INTEGER, created_at INTEGER, revision INTEGER, status TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS questions (id TEXT PRIMARY KEY, listing_id TEXT, author_id TEXT, text TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS offers (id TEXT PRIMARY KEY, listing_id TEXT, buyer_id TEXT, amount_cents INTEGER, counter_amount_cents INTEGER, status TEXT, version INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS agreements (id TEXT PRIMARY KEY, listing_id TEXT UNIQUE, offer_id TEXT UNIQUE, buyer_id TEXT, seller_id TEXT, amount_cents INTEGER)')
            if db.execute('SELECT version FROM initialized').fetchone() is None:
                seed = json.loads(Path(fixture).read_text())
                for user in seed['users']:
                    salt = secrets.token_hex(16)
                    db.execute(
                        'INSERT INTO users VALUES (?,?,?,?,?)',
                        (user['id'], user['username'], user['role'], salt,
                         self.password_hash(user['password'], salt)),
                    )
                for row in seed['listings']:
                    db.execute(
                        'INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?)',
                        (row['id'], row['seller_id'], row['title'],
                         row['price_cents'], row['reference_price_cents'],
                         row['previous_price_cents'], row['created_at'], 0,
                         'active'),
                    )
                db.execute('INSERT INTO initialized VALUES (1)')

    @contextmanager
    def transaction(self):
        # A process-local lock avoids interleaving Store operations, while
        # BEGIN IMMEDIATE also serializes competing requests at the database
        # boundary and makes each domain mutation all-or-nothing.
        with self.lock:
            db = sqlite3.connect(self.database, timeout=30)
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

    @staticmethod
    def password_hash(password, salt):
        return hashlib.pbkdf2_hmac(
            'sha256', password.encode(), bytes.fromhex(salt), 120000
        ).hex()

    @staticmethod
    def user_value(row):
        return {key: row[key] for key in ('id', 'username', 'role')}

    @staticmethod
    def listing_value_from_row(row, labels):
        return {
            'id': row['id'],
            'seller_id': row['seller_id'],
            'title': row['title'],
            'price_cents': row['price_cents'],
            'reference_price_cents': row['reference_price_cents'],
            'previous_price_cents': row['previous_price_cents'],
            'created_at': row['created_at'],
            'revision': row['revision'],
            'status': row['status'],
            'labels': labels,
        }

    @staticmethod
    def offer_value(row):
        return {
            'id': row['id'],
            'listing_id': row['listing_id'],
            'buyer_id': row['buyer_id'],
            'amount_cents': row['amount_cents'],
            'counter_amount_cents': row['counter_amount_cents'],
            'status': row['status'],
            'version': row['version'],
        }

    @staticmethod
    def agreement_value(row):
        return {
            'id': row['id'],
            'listing_id': row['listing_id'],
            'offer_id': row['offer_id'],
            'buyer_id': row['buyer_id'],
            'seller_id': row['seller_id'],
            'amount_cents': row['amount_cents'],
        }

    def login(self, body):
        if not isinstance(body.get('username'), str) or not isinstance(body.get('password'), str):
            invalid()
        with self.transaction() as db:
            row = db.execute(
                'SELECT * FROM users WHERE username=?', (body['username'],)
            ).fetchone()
            if row is None or not hmac.compare_digest(
                self.password_hash(body['password'], row['salt']), row['password']
            ):
                raise Failure(401, 'unauthenticated')
            # token_urlsafe(32) is backed by at least 32 random bytes and is
            # retained only in this process's session map.
            token = secrets.token_urlsafe(32)
            self.sessions[token] = self.user_value(row)
            return {'token': token, 'user': self.user_value(row)}

    def actor(self, authorization):
        with self.lock:
            token = authorization[7:] if authorization.startswith('Bearer ') else ''
            if token not in self.sessions:
                raise Failure(401, 'unauthenticated')
            return dict(self.sessions[token])

    def logout(self, authorization):
        with self.lock:
            self.actor(authorization)
            del self.sessions[authorization[7:]]
        return {'ok': True}

    def now(self):
        value = json.loads(self.clock.read_text())['now']
        if type(value) is not int or value < 0:
            raise RuntimeError('Prepared clock is invalid')
        return value

    @staticmethod
    def listing_row(db, key):
        row = db.execute('SELECT * FROM listings WHERE id=?', (key,)).fetchone()
        if row is None:
            raise Failure(404, 'not_found')
        return row

    @staticmethod
    def offer_row(db, user, key):
        # This lookup deliberately applies the offer visibility rule before
        # returning a row.  Thus a buyer cannot probe or mutate another
        # buyer's offer, and an unrelated seller receives the same 404.
        row = db.execute(
            'SELECT offers.* FROM offers '
            'JOIN listings ON listings.id=offers.listing_id '
            'WHERE offers.id=? AND '
            '(offers.buyer_id=? OR listings.seller_id=?)',
            (key, user['id'], user['id']),
        ).fetchone()
        if row is None:
            raise Failure(404, 'not_found')
        return row

    @staticmethod
    def labels(row, now):
        """Return the live, deterministic labels for one persisted listing."""
        if row['status'] != 'active':
            return []
        labels = []
        reference = row['reference_price_cents']
        if reference is not None and row['price_cents'] <= (reference * 9) // 10:
            labels.append('great_value')
        age = now - row['created_at']
        if 0 <= age <= 604800:
            labels.append('recently_listed')
        previous = row['previous_price_cents']
        if previous is not None and previous > row['price_cents']:
            labels.append('just_reduced')
        return labels

    def listing_value(self, row, now=None):
        if now is None:
            now = self.now()
        return self.listing_value_from_row(row, self.labels(row, now))

    def catalog(self, user):
        with self.transaction() as db:
            now = self.now()
            return {
                'user': user,
                'now': now,
                'listings': [
                    self.listing_value(row, now)
                    for row in db.execute('SELECT * FROM listings ORDER BY rowid')
                ],
            }

    def detail(self, user, key):
        with self.transaction() as db:
            listing = self.listing_row(db, key)
            questions = []
            for row in db.execute(
                'SELECT questions.*,users.username FROM questions '
                'JOIN users ON users.id=questions.author_id '
                'WHERE questions.listing_id=? ORDER BY questions.rowid',
                (key,),
            ):
                questions.append({
                    'id': row['id'],
                    'listing_id': row['listing_id'],
                    'author': {
                        'id': row['author_id'],
                        'username': row['username'],
                    },
                    'text': row['text'],
                })
            offer_rows = db.execute(
                'SELECT offers.* FROM offers '
                'WHERE offers.listing_id=? AND '
                '(offers.buyer_id=? OR ?=(SELECT seller_id FROM listings WHERE id=?)) '
                'ORDER BY offers.rowid',
                (key, user['id'], user['id'], key),
            )
            return {
                'listing': self.listing_value(listing),
                'questions': questions,
                'offers': [self.offer_value(row) for row in offer_rows],
            }

    def questions(self, user, key, body):
        text = body.get('text')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
            invalid()
        with self.transaction() as db:
            row = self.listing_row(db, key)
            if user['role'] != 'buyer':
                forbidden()
            if row['status'] != 'active':
                conflict()
            value = {
                'id': secrets.token_urlsafe(18),
                'listing_id': key,
                'author': {'id': user['id'], 'username': user['username']},
                'text': text.strip(),
            }
            db.execute(
                'INSERT INTO questions VALUES (?,?,?,?)',
                (value['id'], key, user['id'], value['text']),
            )
            return {'question': value}

    def place_offer(self, user, key, body):
        amount = cents(body.get('amount_cents'))
        with self.transaction() as db:
            row = self.listing_row(db, key)
            if user['role'] != 'buyer':
                forbidden()
            if row['status'] != 'active':
                conflict()
            if amount > row['price_cents']:
                invalid()
            offer_id = secrets.token_urlsafe(18)
            db.execute(
                'INSERT INTO offers VALUES (?,?,?,?,?,?,?)',
                (offer_id, key, user['id'], amount, None, 'pending', 0),
            )
            offer = db.execute('SELECT * FROM offers WHERE id=?', (offer_id,)).fetchone()
            return {'offer': self.offer_value(offer)}

    def change_price(self, user, key, body):
        price = cents(body.get('price_cents'))
        revision = integer(body.get('revision'))
        with self.transaction() as db:
            row = self.listing_row(db, key)
            if user['role'] != 'seller' or user['id'] != row['seller_id']:
                forbidden()
            if row['status'] != 'active':
                conflict()
            if row['revision'] != revision:
                conflict()
            if price != row['price_cents']:
                db.execute(
                    'UPDATE listings SET previous_price_cents=?, price_cents=?, revision=? WHERE id=?',
                    (row['price_cents'], price, row['revision'] + 1, key),
                )
            current = self.listing_row(db, key)
            return {'listing': self.listing_value(current)}

    def counter(self, user, key, body):
        amount = cents(body.get('amount_cents'))
        version = integer(body.get('version'))
        with self.transaction() as db:
            offer = self.offer_row(db, user, key)
            listing = self.listing_row(db, offer['listing_id'])
            if user['role'] != 'seller' or user['id'] != listing['seller_id']:
                forbidden()
            if listing['status'] != 'active' or offer['status'] != 'pending' or offer['version'] != version:
                conflict()
            if amount > listing['price_cents']:
                invalid()
            db.execute(
                'UPDATE offers SET counter_amount_cents=?, status=?, version=? WHERE id=?',
                (amount, 'countered', offer['version'] + 1, offer['id']),
            )
            current = db.execute('SELECT * FROM offers WHERE id=?', (offer['id'],)).fetchone()
            return {'offer': self.offer_value(current)}

    def accept(self, user, key, body):
        version = integer(body.get('version'))
        with self.transaction() as db:
            offer = self.offer_row(db, user, key)
            listing = self.listing_row(db, offer['listing_id'])
            if user['role'] != 'buyer' or user['id'] != offer['buyer_id']:
                forbidden()

            # An accepted offer is an idempotent replay.  The caller still
            # has to be the stored buyer and the version still has to be a
            # well-formed nonnegative integer, but it need not be current.
            if offer['status'] == 'accepted':
                agreement = db.execute(
                    'SELECT * FROM agreements WHERE offer_id=?', (offer['id'],)
                ).fetchone()
                if agreement is None:
                    # This is not a state produced by this Store.  Treat it
                    # as a business conflict rather than inventing a record.
                    conflict()
                return {
                    'agreement': self.agreement_value(agreement),
                    'listing': self.listing_value(listing),
                    'offer': self.offer_value(offer),
                }

            if (
                listing['status'] != 'active'
                or offer['status'] != 'countered'
                or offer['version'] != version
                or offer['counter_amount_cents'] is None
            ):
                conflict()

            # The transaction is held for the complete sale.  The listing's
            # unique agreement constraint is an additional database guard,
            # while the active-listing check prevents competing accepts from
            # both succeeding.
            existing = db.execute(
                'SELECT id FROM agreements WHERE listing_id=? OR offer_id=?',
                (listing['id'], offer['id']),
            ).fetchone()
            if existing is not None:
                conflict()

            agreement_id = secrets.token_urlsafe(18)
            db.execute(
                'INSERT INTO agreements VALUES (?,?,?,?,?,?)',
                (
                    agreement_id,
                    listing['id'],
                    offer['id'],
                    offer['buyer_id'],
                    listing['seller_id'],
                    offer['counter_amount_cents'],
                ),
            )
            db.execute(
                'UPDATE offers SET status=?, version=? WHERE id=?',
                ('accepted', offer['version'] + 1, offer['id']),
            )
            db.execute(
                "UPDATE offers SET status='closed', version=version+1 "
                "WHERE listing_id=? AND id<>? AND status IN ('pending','countered')",
                (listing['id'], offer['id']),
            )
            updated_listing = db.execute(
                "UPDATE listings SET status='sold', revision=revision+1 "
                "WHERE id=? AND status='active'",
                (listing['id'],),
            )
            if updated_listing.rowcount != 1:
                # Normally impossible under BEGIN IMMEDIATE, but preserve
                # atomicity if the schema is modified unexpectedly.
                conflict()

            agreement = db.execute(
                'SELECT * FROM agreements WHERE id=?', (agreement_id,)
            ).fetchone()
            accepted_offer = db.execute(
                'SELECT * FROM offers WHERE id=?', (offer['id'],)
            ).fetchone()
            sold_listing = self.listing_row(db, listing['id'])
            return {
                'agreement': self.agreement_value(agreement),
                'listing': self.listing_value(sold_listing),
                'offer': self.offer_value(accepted_offer),
            }

    def agreements(self, user):
        with self.transaction() as db:
            return {
                'agreements': [
                    self.agreement_value(row)
                    for row in db.execute(
                        'SELECT * FROM agreements WHERE buyer_id=? OR seller_id=? ORDER BY rowid',
                        (user['id'], user['id']),
                    )
                ]
            }
