"""Independent photo-chat service. Only synthetic fixtures belong in this project."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image, ImageOps
import os, json, sqlite3, secrets, hashlib, hmac, time, re, base64, io, urllib.parse

class Error(Exception):

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status

class Store:

    def __init__(self, path, config, assets):
        self.config = config
        self._memory_keeper = None
        if os.fspath(path) == ':memory:':
            # sqlite normally creates a new database for every connection to
            # ':memory:'.  A shared URI plus a keeper connection makes the
            # Store API behave consistently for direct in-memory tests too.
            self.path = 'file:photo-chat-%x?mode=memory&cache=shared' % id(self)
            self._uri = True
            self._memory_keeper = sqlite3.connect(self.path, uri=True, timeout=10)
        else:
            self.path = path
            self._uri = False
            state_parent = Path(path).parent
            state_parent.mkdir(parents=True, exist_ok=True)
        self.assets = Path(assets)
        self.assets.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,salt TEXT,verifier TEXT);CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user TEXT);CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,room TEXT,sender TEXT,mode TEXT,caption TEXT,created REAL);CREATE TABLE IF NOT EXISTS opened(request TEXT,user TEXT,at REAL,PRIMARY KEY(request,user));CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY,request TEXT,user TEXT,filename TEXT,created REAL,elapsed REAL,eligible INTEGER,UNIQUE(request,user));CREATE TABLE IF NOT EXISTS contacts(owner TEXT,peer TEXT,PRIMARY KEY(owner,peer));')
            for user in config['users']:
                salt = secrets.token_hex(16)
                db.execute('INSERT OR IGNORE INTO users VALUES(?,?,?)', (user['id'], salt, self.digest(user['password'], salt)))

    def db(self):
        db = sqlite3.connect(self.path, uri=self._uri, timeout=10)
        db.execute('PRAGMA busy_timeout = 10000')
        db.row_factory = sqlite3.Row
        return db

    def digest(self, password, salt):
        if not isinstance(password, str):
            password = ''
        return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

    def login(self, a):
        if not isinstance(a, dict):
            raise Error('invalid_input')
        supplied_user = a.get('user')
        supplied_password = a.get('password', '')
        if not isinstance(supplied_user, str) or not isinstance(supplied_password, str):
            raise Error('invalid_login', 401)
        with self.db() as db:
            row = db.execute('SELECT * FROM users WHERE id=?', (supplied_user,)).fetchone()
            if not row or not hmac.compare_digest(row['verifier'], self.digest(supplied_password, row['salt'])):
                raise Error('invalid_login', 401)
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), row['id']))
            return {'token': token}

    def actor(self, token):
        if not isinstance(token, str):
            raise Error('unauthorized', 401)
        with self.db() as db:
            row = db.execute('SELECT user FROM sessions WHERE hash=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row:
            raise Error('unauthorized', 401)
        return row['user']

    def room(self, user, rid):
        room = next((r for r in self.config['rooms'] if r['id'] == rid), None)
        if not room or user not in room['members']:
            raise Error('not_found', 404)
        return room

    def request(self, db, user, rid):
        if not isinstance(rid, str) or not rid:
            raise Error('not_found', 404)
        row = db.execute('SELECT * FROM requests WHERE id=?', (rid,)).fetchone()
        if not row:
            raise Error('not_found', 404)
        self.room(user, row['room'])
        return row

    def targets(self, row):
        """Return the recipients implied by a request's mode.

        A Duo is a room-wide moment: the sender participates just like every
        other room member.  Ask and Challenge are responses requested from
        the other members only.  The recipient set is derived from the
        server-owned room fixture rather than from request input, so a caller
        cannot add an arbitrary user to a request.
        """
        room = self.room(row['sender'], row['room'])
        if row['mode'] == 'duo':
            return list(room['members'])
        return [u for u in room['members'] if u != row['sender']]

    def normalize(self, value):
        """Normalize one supplied phone number using the fixture convention."""
        if not isinstance(value, str):
            raise Error('invalid_phone')
        # The component deliberately implements only the documented, local
        # convention.  It is not a general address-book phone parser.
        value = re.sub(r'[\s()\-]', '', value)
        if value.startswith('00'):
            value = '+' + value[2:]
        if not re.fullmatch(r'\+[1-9][0-9]{7,14}', value):
            raise Error('invalid_phone')
        return value

    def _valid_image(self, encoded):
        """Decode a supplied JPEG and return a metadata-free JPEG payload."""
        if not isinstance(encoded, str):
            raise Error('invalid_image')
        try:
            raw = base64.b64decode(encoded, validate=True)
            if not raw or len(raw) > 4000000:
                raise ValueError()
            with Image.open(io.BytesIO(raw)) as source:
                # The public endpoint accepts the documented upload type.  A
                # fresh JPEG is then written below, so source EXIF, ICC and
                # other ancillary metadata cannot be carried into storage.
                if source.format != 'JPEG':
                    raise ValueError()
                if source.width <= 0 or source.height <= 0 or source.width * source.height > 12000000:
                    raise ValueError()
                source.load()
                picture = ImageOps.exif_transpose(source).convert('RGB')
                clean = Image.new('RGB', picture.size)
                clean.paste(picture)
                buffer = io.BytesIO()
                clean.save(buffer, format='JPEG', quality=90, exif=b'')
                return buffer.getvalue()
        except Error:
            raise
        except Exception:
            raise Error('invalid_image')

    def act(self, authenticated_user, path, action):
        """Perform one authenticated mutation and return its persisted result."""
        if not isinstance(action, dict):
            raise Error('invalid_input')
        user = authenticated_user
        with self.db() as db:
            if path == '/requests':
                if 'room' not in action:
                    raise Error('invalid_input')
                room_id = action.get('room')
                room = self.room(user, room_id)
                request_id = action.get('id')
                mode = action.get('mode')
                caption = action.get('caption', '')
                if (
                    not isinstance(request_id, str)
                    or not request_id
                    or mode not in ('ask', 'duo', 'challenge')
                    or not isinstance(caption, str)
                    or len(caption) > 500
                ):
                    raise Error('invalid_request')

                # Lock before looking up the stable ID.  This makes retries
                # idempotent even when two HTTP workers submit them together.
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
                if old:
                    if (old['room'], old['sender'], old['mode'], old['caption']) != (
                        room['id'], user, mode, caption
                    ):
                        raise Error('request_conflict', 409)
                    return {**dict(old), 'targets': self.targets(old)}
                row = {
                    'id': request_id,
                    'room': room['id'],
                    'sender': user,
                    'mode': mode,
                    'caption': caption,
                    'created': time.time(),
                }
                db.execute(
                    'INSERT INTO requests(id,room,sender,mode,caption,created) '
                    'VALUES(:id,:room,:sender,:mode,:caption,:created)',
                    row,
                )
                return {**row, 'targets': self.targets(row)}

            if path == '/open':
                if 'request' not in action:
                    raise Error('invalid_input')
                request_id = action.get('request')
                row = self.request(db, user, request_id)
                if user not in self.targets(row):
                    raise Error('not_recipient', 403)
                db.execute('BEGIN IMMEDIATE')
                # Re-opening never resets the server-side clock.  A browser
                # refresh therefore cannot extend the response window.
                db.execute(
                    'INSERT OR IGNORE INTO opened(request,user,at) VALUES(?,?,?)',
                    (row['id'], user, time.time()),
                )
                return {'request': row['id'], 'countdown': self.config.get('countdown', 3)}

            if path == '/respond':
                if 'request' not in action:
                    raise Error('invalid_input')
                request_id = action.get('request')
                row = self.request(db, user, request_id)
                if user not in self.targets(row):
                    raise Error('not_recipient', 403)
                db.execute('BEGIN IMMEDIATE')
                old = db.execute(
                    'SELECT * FROM photos WHERE request=? AND user=?',
                    (row['id'], user),
                ).fetchone()
                if old:
                    # A retry is idempotent and cannot replace the original
                    # response with a second photo.
                    return self.photo_record(db, old)

                opened = db.execute(
                    'SELECT at FROM opened WHERE request=? AND user=?',
                    (row['id'], user),
                ).fetchone()
                now = time.time()
                countdown = self.config.get('countdown', 3)
                if not opened or now - opened['at'] < countdown:
                    raise Error('countdown_not_finished', 409)

                payload = self._valid_image(action.get('image'))
                # elapsed is calculated solely from server timestamps.  The
                # request creation time is the start of the response window;
                # the client cannot submit or override this value.
                elapsed = now - row['created']
                response_window = self.config.get('response_window', 60)
                eligible = 0 <= elapsed <= response_window
                pid = secrets.token_hex(16)
                filename = pid + '.jpg'
                image_path = self.assets / filename
                image_path.write_bytes(payload)
                try:
                    db.execute(
                        'INSERT INTO photos(id,request,user,filename,created,elapsed,eligible) '
                        'VALUES(?,?,?,?,?,?,?)',
                        (pid, row['id'], user, filename, now, elapsed, int(eligible)),
                    )
                except Exception:
                    # Do not leave an apparently accepted asset behind if the
                    # SQLite write is rolled back.
                    try:
                        image_path.unlink()
                    except FileNotFoundError:
                        pass
                    raise
                return self.photo_record(
                    db, db.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
                )

            if path == '/contact':
                numbers = action.get('numbers')
                if (
                    not isinstance(numbers, list)
                    or not 1 <= len(numbers) <= 10
                    or any(not isinstance(number, str) for number in numbers)
                ):
                    raise Error('invalid_contact')
                normalized = {self.normalize(number) for number in numbers}
                matches = []
                for fixture_user in self.config['users']:
                    peer = fixture_user['id']
                    if peer == user:
                        continue
                    registered = set()
                    for phone in fixture_user.get('phones', []):
                        try:
                            registered.add(self.normalize(phone))
                        except Error:
                            # A malformed fixture number must not make an
                            # otherwise valid selected contact unusable.
                            continue
                    if registered & normalized:
                        matches.append(peer)
                matches = sorted(set(matches))
                if matches:
                    for peer in matches:
                        db.execute(
                            'INSERT OR IGNORE INTO contacts(owner,peer) VALUES(?,?)',
                            (user, peer),
                        )
                    return {'action': 'added', 'users': matches}
                return {
                    'action': 'invite',
                    'numbers': sorted(normalized),
                    'body': 'Join the synthetic photo chat.',
                }
            raise Error('not_found', 404)

    def photo_record(self, db, p):
        row = db.execute('SELECT room,caption FROM requests WHERE id=?', (p['request'],)).fetchone()
        return {k: p[k] for k in ['id', 'request', 'user', 'created', 'elapsed', 'eligible']} | dict(row) | {'url': '/photos/' + p['id']}

    def read(self, user, path, q):
        with self.db() as db:
            if path == '/rooms':
                return [r for r in self.config['rooms'] if user in r['members']]
            if path == '/timeline':
                if 'room' not in q:
                    raise Error('invalid_input')
                room = self.room(user, q.get('room'))
                return [
                    self.photo_record(db, p)
                    for p in db.execute(
                        'SELECT photos.* FROM photos '
                        'JOIN requests ON photos.request=requests.id '
                        'WHERE room=? ORDER BY photos.created,photos.id',
                        (room['id'],),
                    )
                ]
            if path == '/requests':
                if 'room' not in q:
                    raise Error('invalid_input')
                room = self.room(user, q.get('room'))
                return [
                    {**dict(r), 'targets': self.targets(r)}
                    for r in db.execute(
                        'SELECT * FROM requests WHERE room=? ORDER BY created,id',
                        (room['id'],),
                    )
                ]
            if path == '/route':
                if 'room' not in q or 'request' not in q:
                    raise Error('invalid_input')
                row = self.request(db, user, q.get('request'))
                if row['room'] != q.get('room'):
                    raise Error('not_found', 404)
                return {
                    'room': row['room'],
                    'request': row['id'],
                    'route': '/rooms/' + row['room'] + '/requests/' + row['id'],
                }
            if path == '/contacts':
                return [r[0] for r in db.execute('SELECT peer FROM contacts WHERE owner=? ORDER BY peer', (user,))]
            raise Error('not_found', 404)

def main():
    config = json.loads(Path(os.environ['PHOTO_CONFIG']).read_text())
    store = Store(os.environ['PHOTO_DATABASE'], config, os.environ['PHOTO_ASSETS'])

    class Handler(BaseHTTPRequestHandler):

        def log_message(self, *a):
            pass

        def send(self, status, data, mime='application/json'):
            raw = json.dumps(data).encode() if mime == 'application/json' else data
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

        def execute(self):
            try:
                parsed = urllib.parse.urlsplit(self.path)
                path = parsed.path
                size = int(self.headers.get('Content-Length', '0'))
                if size > 6000000:
                    raise Error('request_too_large', 413)
                a = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(a, dict):
                    raise Error('invalid_input')
                if path == '/' and self.command == 'GET':
                    return self.send(200, (Path(__file__).parent / 'index.html').read_bytes(), 'text/html; charset=utf-8')
                if path == '/login' and self.command == 'POST':
                    return self.send(200, store.login(a))
                token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                user = store.actor(token)
                if path == '/logout' and self.command == 'POST':
                    with store.db() as db:
                        db.execute('DELETE FROM sessions WHERE hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
                    return self.send(200, {})
                if path.startswith('/photos/') and self.command == 'GET':
                    photo_id = path[len('/photos/'):]
                    with store.db() as db:
                        photo = db.execute(
                            'SELECT * FROM photos WHERE id=?', (photo_id,)
                        ).fetchone()
                        if not photo:
                            raise Error('not_found', 404)
                        # The membership check is deliberately performed from
                        # the request's room, not from the photo URL.
                        store.request(db, user, photo['request'])
                        try:
                            payload = (store.assets / photo['filename']).read_bytes()
                        except OSError:
                            raise Error('not_found', 404)
                        return self.send(200, payload, 'image/jpeg')
                return self.send(200, store.read(user, path, {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}) if self.command == 'GET' else store.act(user, path, a))
            except Error as e:
                self.send(e.status, {'error': e.message})
            except sqlite3.IntegrityError:
                self.send(409, {'error': 'conflict'})
            except (KeyError, ValueError, TypeError):
                self.send(400, {'error': 'invalid_input'})
        do_GET = execute
        do_POST = execute
    server = ThreadingHTTPServer(('127.0.0.1', int(os.environ.get('PORT', '0'))), Handler)
    print(server.server_port, flush=True)
    server.serve_forever()
if __name__ == '__main__':
    main()
