"""Independent photo-chat service. Only synthetic fixtures belong in this project."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image, ImageOps
import os, json, sqlite3, secrets, hashlib, hmac, time, re, base64, io, urllib.parse

class Error(Exception):

    def __init__(self, message, status=400):
        self.message = message
        self.status = status

class Store:

    def __init__(self, path, config, assets):
        self.path = path
        self.config = config
        self.assets = Path(assets)
        self.assets.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,salt TEXT,verifier TEXT);CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user TEXT);CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,room TEXT,sender TEXT,mode TEXT,caption TEXT,created REAL);CREATE TABLE IF NOT EXISTS opened(request TEXT,user TEXT,at REAL,PRIMARY KEY(request,user));CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY,request TEXT,user TEXT,filename TEXT,created REAL,elapsed REAL,eligible INTEGER,UNIQUE(request,user));CREATE TABLE IF NOT EXISTS contacts(owner TEXT,peer TEXT,PRIMARY KEY(owner,peer));')
            for user in config['users']:
                salt = secrets.token_hex(16)
                db.execute('INSERT OR IGNORE INTO users VALUES(?,?,?)', (user['id'], salt, self.digest(user['password'], salt)))

    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def digest(self, password, salt):
        return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

    def login(self, a):
        with self.db() as db:
            row = db.execute('SELECT * FROM users WHERE id=?', (a.get('user'),)).fetchone()
            if not row or not hmac.compare_digest(row['verifier'], self.digest(a.get('password', ''), row['salt'])):
                raise Error('invalid_login', 401)
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), row['id']))
            return {'token': token}

    def actor(self, token):
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
        row = db.execute('SELECT * FROM requests WHERE id=?', (rid,)).fetchone()
        if not row:
            raise Error('not_found', 404)
        self.room(user, row['room'])
        return row

    def targets(self, row):
        room = self.room(row['sender'], row['room'])
        return [u for u in room['members'] if u != row['sender']]

    def normalize(self, value):
        value = re.sub('[ ()-]', '', value)
        if value.startswith('00'):
            value = '+' + value[2:]
        if not re.fullmatch('\\+[1-9][0-9]{7,14}', value):
            raise Error('invalid_phone')
        return value

    def act(self, user, path, a):
        with self.db() as db:
            if path == '/requests':
                room = self.room(user, a['room'])
                mode = a['mode']
                caption = a.get('caption', '')
                if mode not in ['ask', 'duo', 'challenge'] or not isinstance(caption, str) or len(caption) > 500 or (not isinstance(a.get('id'), str)) or (not a['id']):
                    raise Error('invalid_request')
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT * FROM requests WHERE id=?', (a['id'],)).fetchone()
                if old:
                    if (old['room'], old['sender'], old['mode'], old['caption']) != (room['id'], user, mode, caption):
                        raise Error('request_conflict', 409)
                    return {**dict(old), 'targets': self.targets(old)}
                row = {'id': a['id'], 'room': room['id'], 'sender': user, 'mode': mode, 'caption': caption, 'created': time.time()}
                db.execute('INSERT INTO requests VALUES(:id,:room,:sender,:mode,:caption,:created)', row)
                return {**row, 'targets': self.targets(row)}
            if path == '/open':
                row = self.request(db, user, a['request'])
                if user not in self.targets(row):
                    raise Error('not_recipient', 403)
                db.execute('INSERT OR IGNORE INTO opened VALUES(?,?,?)', (row['id'], user, time.time()))
                return {'request': row['id'], 'countdown': self.config.get('countdown', 3)}
            if path == '/respond':
                row = self.request(db, user, a['request'])
                if user not in self.targets(row):
                    raise Error('not_recipient', 403)
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT * FROM photos WHERE request=? AND user=?', (row['id'], user)).fetchone()
                if old:
                    return self.photo_record(db, old)
                opened = db.execute('SELECT at FROM opened WHERE request=? AND user=?', (row['id'], user)).fetchone()
                now = time.time()
                if not opened or now - opened['at'] < self.config.get('countdown', 3):
                    raise Error('countdown_not_finished', 409)
                try:
                    raw = base64.b64decode(a['image'], validate=True)
                    if len(raw) > 4000000:
                        raise ValueError()
                    with Image.open(io.BytesIO(raw)) as src:
                        if src.width * src.height > 12000000:
                            raise ValueError()
                        src.load()
                        picture = ImageOps.exif_transpose(src).convert('RGB')
                        clean = Image.new('RGB', picture.size)
                        clean.paste(picture)
                        buffer = io.BytesIO()
                        clean.save(buffer, format='JPEG', quality=90)
                except Exception:
                    raise Error('invalid_image')
                pid = secrets.token_hex(16)
                filename = pid + '.jpg'
                elapsed = now - row['created']
                eligible = elapsed <= self.config.get('response_window', 60)
                (self.assets / filename).write_bytes(buffer.getvalue())
                db.execute('INSERT INTO photos VALUES(?,?,?,?,?,?,?)', (pid, row['id'], user, filename, now, elapsed, int(eligible)))
                return self.photo_record(db, db.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone())
            if path == '/contact':
                numbers = a.get('numbers')
                if not isinstance(numbers, list) or not 1 <= len(numbers) <= 10 or any((not isinstance(x, str) for x in numbers)):
                    raise Error('invalid_contact')
                normalized = {self.normalize(x) for x in numbers}
                matches = [u['id'] for u in self.config['users'] if u['id'] != user and any((self.normalize(n) in normalized for n in u.get('phones', [])))]
                if matches:
                    for peer in matches:
                        db.execute('INSERT OR IGNORE INTO contacts VALUES(?,?)', (user, peer))
                    return {'action': 'added', 'users': sorted(matches)}
                return {'action': 'invite', 'numbers': sorted(normalized), 'body': 'Join the synthetic photo chat.'}
            raise Error('not_found', 404)

    def photo_record(self, db, p):
        row = db.execute('SELECT room,caption FROM requests WHERE id=?', (p['request'],)).fetchone()
        return {k: p[k] for k in ['id', 'request', 'user', 'created', 'elapsed', 'eligible']} | dict(row) | {'url': '/photos/' + p['id']}

    def read(self, user, path, q):
        with self.db() as db:
            if path == '/rooms':
                return [r for r in self.config['rooms'] if user in r['members']]
            if path == '/timeline':
                room = self.room(user, q['room'])
                return [self.photo_record(db, p) for p in db.execute('SELECT photos.* FROM photos JOIN requests ON photos.request=requests.id WHERE room=? ORDER BY photos.created,photos.id', (room['id'],))]
            if path == '/requests':
                room = self.room(user, q['room'])
                return [{**dict(r), 'targets': self.targets(r)} for r in db.execute('SELECT * FROM requests WHERE room=? ORDER BY created,id', (room['id'],))]
            if path == '/route':
                row = self.request(db, user, q['request'])
                if row['room'] != q['room']:
                    raise Error('not_found', 404)
                return {'room': row['room'], 'request': row['id'], 'route': '/rooms/' + row['room'] + '/requests/' + row['id']}
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
                    with store.db() as db:
                        photo = db.execute('SELECT * FROM photos WHERE id=?', (path[8:],)).fetchone()
                        if not photo:
                            raise Error('not_found', 404)
                        request = store.request(db, user, photo['request'])
                        return self.send(200, (store.assets / photo['filename']).read_bytes(), 'image/jpeg')
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
