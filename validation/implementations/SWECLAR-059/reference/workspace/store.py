from contextlib import contextmanager
from pathlib import Path
import base64
import csv
import hashlib
import io
import sqlite3
import time
import warnings

from PIL import Image


FIELDS = ['staff_id', 'supplier_id', 'name', 'birth_city', 'status', 'photo_id']
VALID_STATUSES = {'submitted', 'approved', 'rejected'}
MAX_IMAGE_BYTES = 2_000_000
MAX_IMAGE_PIXELS = 4_000_000


def text(value):
    """Return whether value is a non-empty textual value.

    IDs and form values are deliberately not coerced.  In particular, this
    keeps numbers supplied by a caller from becoming valid identifiers by
    accident, while allowing the caller's action object to remain untouched.
    """
    return isinstance(value, str) and bool(value.strip())


class Store:
    def __init__(self, path, identities):
        self.path = path
        self.identities = identities
        self._connect_target = path
        self._connect_uri = False
        self._memory_keeper = None
        if str(path) == ':memory:':
            # A normal ``:memory:`` database belongs to one SQLite connection,
            # while the store opens short-lived connections per operation.
            # Keep a private shared-memory anchor so that this useful test and
            # embedding mode has the same persistence semantics as a file DB.
            self._connect_target = (
                f'file:registration-store-{id(self)}?mode=memory&cache=shared'
            )
            self._connect_uri = True
            self._memory_keeper = sqlite3.connect(
                self._connect_target, timeout=10, uri=True
            )
            self._memory_keeper.execute('PRAGMA foreign_keys=ON')
            self._memory_keeper.execute('PRAGMA busy_timeout=10000')

        # The database is supplied by the deployment/test harness.  Creating
        # the parent is useful for a fresh configured path and does not expose
        # any of the files through the HTTP server.
        if isinstance(path, (str, Path)) and str(path) not in {':memory:', ''}:
            parent = Path(path).expanduser().parent
            parent.mkdir(parents=True, exist_ok=True)

        db = self.connect()
        try:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS suppliers(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS photos(
                    id TEXT PRIMARY KEY,
                    supplier_id TEXT NOT NULL REFERENCES suppliers(id),
                    data BLOB NOT NULL,
                    digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS staff(
                    id TEXT PRIMARY KEY,
                    supplier_id TEXT NOT NULL REFERENCES suppliers(id),
                    name TEXT NOT NULL,
                    birth_city TEXT NOT NULL,
                    status TEXT NOT NULL,
                    photo_id TEXT REFERENCES photos(id)
                );
                CREATE TABLE IF NOT EXISTS audit(
                    seq INTEGER PRIMARY KEY,
                    staff_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    old_status TEXT,
                    new_status TEXT,
                    timestamp INTEGER
                );
                CREATE TABLE IF NOT EXISTS photo_history(
                    seq INTEGER PRIMARY KEY,
                    staff_id TEXT NOT NULL,
                    photo_id TEXT NOT NULL REFERENCES photos(id)
                );
                """
            )
            db.commit()
        finally:
            db.close()

    def connect(self):
        """Open a connection with the safety settings required by the store."""
        db = sqlite3.connect(
            self._connect_target,
            timeout=10,
            uri=self._connect_uri,
        )
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=10000')
        return db

    @contextmanager
    def _transaction(self):
        """Return a context-managed, write-locked SQLite connection.

        ``BEGIN IMMEDIATE`` makes validation and the subsequent write one
        serialized operation.  The connection context rolls back every
        exception, including validation errors raised after earlier writes.
        """
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def identity(self, token):
        """Resolve a token only from the private configured identities."""
        try:
            user = self.identities.get(token)
        except (AttributeError, TypeError):
            user = None
        if not isinstance(user, dict):
            raise PermissionError('unauthorized')

        # A malformed deployment identity must not accidentally acquire a
        # role or scope.  These values are configuration, never action input.
        role = user.get('role')
        if role not in {'review', 'supplier'} or not text(user.get('id')):
            raise PermissionError('unauthorized')
        if role == 'supplier' and not text(user.get('supplier_id')):
            raise PermissionError('unauthorized')
        return user

    def allowed(self, user, supplier):
        """Whether an authenticated identity may access one supplier."""
        if user.get('role') == 'review':
            return True
        return (
            user.get('role') == 'supplier'
            and text(supplier)
            and user.get('supplier_id') == supplier
        )

    def require_review(self, user):
        if user.get('role') != 'review':
            raise PermissionError('review_required')

    @staticmethod
    def _required_action_fields(action, fields):
        if not all(text(action.get(field)) for field in fields):
            raise ValueError('invalid_request')

    @staticmethod
    def _canonical_image(encoded, media_type):
        """Decode and canonicalize one uploaded PNG/JPEG image.

        The returned value is always a freshly encoded PNG.  No source image
        metadata is passed to Pillow's encoder.
        """
        if not isinstance(encoded, str):
            raise ValueError('invalid_image')
        if not isinstance(media_type, str):
            raise ValueError('invalid_image')
        # Whitespace is permitted by the base64 representation, but is
        # removed only in this local value; the caller's action is untouched.
        encoded = ''.join(encoded.split())
        # Reject oversized encoded payloads before asking the decoder to
        # allocate the decoded buffer.  Padding can add at most a few bytes.
        if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 4:
            raise ValueError('invalid_image')

        media = media_type.lower()
        expected = {
            'image/png': 'PNG',
            'image/jpeg': 'JPEG',
            # image/jpg is a commonly supplied spelling, but the bytes still
            # have to be a real JPEG below.
            'image/jpg': 'JPEG',
        }.get(media)
        if expected is None:
            raise ValueError('invalid_image')

        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ValueError('invalid_image')
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('invalid_image')

        try:
            # Treat decompression warnings as failures in addition to the
            # explicit pixel bound.  This keeps malformed/bomb-like inputs
            # from being partially accepted by an image plugin.
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                # Verify the encoded stream first, then reopen it for the
                # pixel decode (Pillow's verify() invalidates the first image
                # object).  This rejects truncated files that some plugins
                # can otherwise partially load.
                with Image.open(io.BytesIO(raw)) as probe:
                    if probe.format != expected:
                        raise ValueError('invalid_image')
                    width, height = probe.size
                    if (
                        not isinstance(width, int)
                        or not isinstance(height, int)
                        or width <= 0
                        or height <= 0
                        or width * height > MAX_IMAGE_PIXELS
                    ):
                        raise ValueError('invalid_image')
                    probe.verify()

                with Image.open(io.BytesIO(raw)) as source:
                    # Palette/CMYK/etc. images are converted to a normal PNG
                    # colour mode.  For common modes a copy retains pixels;
                    # clearing ``info`` ensures EXIF, ICC, textual PNG data,
                    # and similar source metadata cannot be propagated.
                    source.load()
                    if source.mode == 'P':
                        mode = 'RGBA' if 'transparency' in source.info else 'RGB'
                        image = source.convert(mode)
                    elif source.mode in {'1', 'L', 'LA', 'RGB', 'RGBA', 'I', 'I;16'}:
                        image = source.copy()
                    else:
                        image = source.convert('RGBA' if 'A' in source.mode else 'RGB')
                    image.info.clear()

                    output = io.BytesIO()
                    image.save(output, format='PNG')
                    image.close()
                    canonical = output.getvalue()
        except ValueError:
            raise
        except Exception:
            # Pillow raises several plugin-specific exceptions for truncated
            # or malformed files.  They are all invalid API input.
            raise ValueError('invalid_image')

        if not canonical:
            raise ValueError('invalid_image')
        return canonical

    @staticmethod
    def _parse_import(value):
        """Parse and structurally validate an exact-column CSV payload."""
        if isinstance(value, bytes):
            try:
                value = value.decode('utf-8')
            except UnicodeDecodeError:
                raise ValueError('invalid_csv')
        if not isinstance(value, str):
            raise ValueError('invalid_csv')
        # The CSV module's small default field limit is not a business rule;
        # permit valid quoted names/cities up to the payload already held in
        # memory.  Only increase the process-wide limit, so concurrent parses
        # cannot lower one another's limit.
        csv.field_size_limit(max(csv.field_size_limit(), len(value) + 1))

        try:
            reader = csv.reader(io.StringIO(value, newline=''), strict=True)
            header = next(reader)
            # Accept the conventional UTF-8 BOM without changing any data
            # field.  It is still required to resolve to exactly the declared
            # six columns.
            if header and header[0].startswith('\ufeff'):
                header[0] = header[0][1:]
            if (
                len(header) != len(FIELDS)
                or len(set(header)) != len(FIELDS)
                or set(header) != set(FIELDS)
            ):
                raise ValueError('invalid_csv')

            positions = {field: header.index(field) for field in FIELDS}
            rows = []
            for values in reader:
                if len(values) != len(FIELDS):
                    raise ValueError('invalid_csv')
                rows.append({field: values[positions[field]] for field in FIELDS})
        except StopIteration:
            raise ValueError('invalid_csv')
        except csv.Error:
            raise ValueError('invalid_csv')
        return rows

    def action(self, token, action):
        """Perform one authenticated registration operation transactionally."""
        user = self.identity(token)
        if not isinstance(action, dict):
            raise ValueError('invalid_request')

        # Work on a shallow copy and never write to ``action``.  The delivery
        # adapter deliberately checks this property for callers.
        a = dict(action)
        kind = a.get('type')

        if kind == 'upload_photo':
            self._required_action_fields(a, ['asset_id', 'supplier_id'])
            asset_id = a['asset_id']
            supplier_id = a['supplier_id']
            if not self.allowed(user, supplier_id):
                raise PermissionError('supplier_denied')
            canonical = self._canonical_image(a.get('data'), a.get('media_type'))
            digest = hashlib.sha256(canonical).hexdigest()
            with self._transaction() as db:
                if not db.execute(
                    'SELECT 1 FROM suppliers WHERE id=?', (supplier_id,)
                ).fetchone():
                    raise ValueError('unknown_supplier')
                db.execute(
                    'INSERT INTO photos(id,supplier_id,data,digest) VALUES (?,?,?,?)',
                    (asset_id, supplier_id, sqlite3.Binary(canonical), digest),
                )
            return {'asset_id': asset_id}

        if kind == 'import':
            self.require_review(user)
            rows = self._parse_import(a.get('csv'))
            with self._transaction() as db:
                self._validate_import_rows(db, rows)
                db.executemany(
                    """
                    INSERT INTO staff(
                        id,supplier_id,name,birth_city,status,photo_id
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    [
                        (
                            row['staff_id'],
                            row['supplier_id'],
                            row['name'],
                            row['birth_city'],
                            row['status'],
                            row['photo_id'] or None,
                        )
                        for row in rows
                    ],
                )
            return {'imported': len(rows)}

        # All remaining operations are ordinary SQLite transactions.  Keeping
        # the lock around validation and the write is important for duplicate
        # requests arriving at the same time.
        with self._transaction() as db:
            if kind == 'add_supplier':
                self.require_review(user)
                self._required_action_fields(a, ['supplier_id', 'name'])
                supplier_id = a['supplier_id']
                db.execute(
                    'INSERT INTO suppliers(id,name) VALUES (?,?)',
                    (supplier_id, a['name'].strip()),
                )
                return {'supplier_id': supplier_id}

            if kind == 'register_staff':
                self._required_action_fields(
                    a, ['staff_id', 'supplier_id', 'name', 'birth_city']
                )
                supplier_id = a['supplier_id']
                if not self.allowed(user, supplier_id):
                    raise PermissionError('supplier_denied')
                if not db.execute(
                    'SELECT 1 FROM suppliers WHERE id=?', (supplier_id,)
                ).fetchone():
                    raise ValueError('unknown_supplier')
                staff_id = a['staff_id']
                db.execute(
                    """
                    INSERT INTO staff(
                        id,supplier_id,name,birth_city,status,photo_id
                    ) VALUES (?,?,?,?,?,NULL)
                    """,
                    (
                        staff_id,
                        supplier_id,
                        a['name'].strip(),
                        a['birth_city'].strip(),
                        'submitted',
                    ),
                )
                return {'staff_id': staff_id}

            if kind == 'review':
                self.require_review(user)
                self._required_action_fields(a, ['staff_id', 'status'])
                status = a['status']
                if status not in {'approved', 'rejected'}:
                    raise ValueError('invalid_status')
                staff_id = a['staff_id']
                row = db.execute(
                    'SELECT status FROM staff WHERE id=?', (staff_id,)
                ).fetchone()
                if row is None:
                    raise ValueError('unknown_staff')
                if row['status'] != 'submitted':
                    raise ValueError('already_reviewed')

                # Actor and timestamp are intentionally obtained here, not
                # from the action object.  The conditional state check above
                # is protected by the write lock.
                timestamp = int(time.time())
                db.execute(
                    'UPDATE staff SET status=? WHERE id=? AND status=?',
                    (status, staff_id, 'submitted'),
                )
                db.execute(
                    """
                    INSERT INTO audit(
                        staff_id,actor_id,old_status,new_status,timestamp
                    ) VALUES (?,?,?,?,?)
                    """,
                    (staff_id, user['id'], 'submitted', status, timestamp),
                )
                return {'staff_id': staff_id, 'status': status}

            if kind == 'attach_photo':
                self._required_action_fields(a, ['staff_id', 'asset_id'])
                staff_id = a['staff_id']
                asset_id = a['asset_id']
                staff = db.execute(
                    'SELECT id,supplier_id,photo_id FROM staff WHERE id=?',
                    (staff_id,),
                ).fetchone()
                if staff is None:
                    raise ValueError('unknown_staff')
                if not self.allowed(user, staff['supplier_id']):
                    raise PermissionError('staff_denied')
                photo = db.execute(
                    'SELECT id,supplier_id FROM photos WHERE id=?',
                    (asset_id,),
                ).fetchone()
                if photo is None:
                    raise ValueError('unknown_photo')
                if photo['supplier_id'] != staff['supplier_id']:
                    raise PermissionError('photo_denied')

                # Attaching the current image again is a successful no-op:
                # importantly, it does not create another history entry.
                if staff['photo_id'] == asset_id:
                    return {'staff_id': staff_id, 'photo_id': asset_id}

                # The history stores replaced/currently former IDs in order.
                # The current image is represented by staff.photo_id, while
                # every distinct replacement preserves the ID it displaced.
                if staff['photo_id'] is not None:
                    db.execute(
                        'INSERT INTO photo_history(staff_id,photo_id) VALUES (?,?)',
                        (staff_id, staff['photo_id']),
                    )
                db.execute(
                    'UPDATE staff SET photo_id=? WHERE id=?',
                    (asset_id, staff_id),
                )
                return {'staff_id': staff_id, 'photo_id': asset_id}

            raise ValueError('unknown_action')

    @staticmethod
    def _validate_import_rows(db, rows):
        seen = set()
        for row in rows:
            staff_id = row['staff_id']
            supplier_id = row['supplier_id']
            if (
                not text(staff_id)
                or not text(supplier_id)
                or not text(row['name'])
                or not text(row['birth_city'])
                or row['status'] not in VALID_STATUSES
            ):
                raise ValueError('invalid_csv')
            if staff_id in seen:
                raise ValueError('conflicting_staff')
            seen.add(staff_id)

            if not db.execute(
                'SELECT 1 FROM suppliers WHERE id=?', (supplier_id,)
            ).fetchone():
                raise ValueError('unknown_supplier')
            if db.execute(
                'SELECT 1 FROM staff WHERE id=?', (staff_id,)
            ).fetchone():
                raise ValueError('conflicting_staff')

            photo_id = row['photo_id']
            if photo_id:
                photo = db.execute(
                    'SELECT supplier_id FROM photos WHERE id=?', (photo_id,)
                ).fetchone()
                if photo is None or photo['supplier_id'] != supplier_id:
                    raise ValueError('invalid_photo')

    def list_staff(self, token):
        user = self.identity(token)
        db = self.connect()
        try:
            rows = db.execute(
                """
                SELECT id AS staff_id,supplier_id,name,birth_city,status,photo_id
                FROM staff ORDER BY id
                """
            ).fetchall()
            return [dict(row) for row in rows if self.allowed(user, row['supplier_id'])]
        finally:
            db.close()

    def export(self, token):
        self.require_review(self.identity(token))
        db = self.connect()
        try:
            rows = db.execute(
                """
                SELECT id AS staff_id,supplier_id,name,birth_city,status,photo_id
                FROM staff ORDER BY id
                """
            ).fetchall()
            output = io.StringIO(newline='')
            writer = csv.DictWriter(
                output,
                fieldnames=FIELDS,
                lineterminator='\r\n',
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        field: (row[field] if row[field] is not None else '')
                        for field in FIELDS
                    }
                )
            return output.getvalue().encode('utf-8')
        finally:
            db.close()

    def photo(self, token, ident):
        user = self.identity(token)
        db = self.connect()
        try:
            row = db.execute(
                'SELECT data,supplier_id FROM photos WHERE id=?', (ident,)
            ).fetchone()
            if row is None or not self.allowed(user, row['supplier_id']):
                raise PermissionError('photo_denied')
            return bytes(row['data'])
        finally:
            db.close()

    def history(self, token):
        self.require_review(self.identity(token))
        db = self.connect()
        try:
            return {
                'audit': [
                    dict(row)
                    for row in db.execute('SELECT * FROM audit ORDER BY seq')
                ],
                'photo_history': [
                    dict(row)
                    for row in db.execute(
                        'SELECT * FROM photo_history ORDER BY seq'
                    )
                ],
            }
        finally:
            db.close()
