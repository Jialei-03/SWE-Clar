<?php
declare(strict_types=1);

const FIELDS = ['document_id', 'name', 'group', 'contact', 'reviewer', 'reference'];
const SLOTS = ['front_left', 'front_right', 'back', 'watermark'];

final class ApiError extends RuntimeException
{
    public function __construct(
        public int $status,
        public string $kind,
        string $message = ''
    ) {
        parent::__construct($message !== '' ? $message : str_replace('_', ' ', $kind));
    }
}

function fail(int $status, string $code, string $message = ''): never
{
    throw new ApiError($status, $code, $message);
}

function directory(): string
{
    $configured = getenv('DOCUMENT_DATA_DIR');
    return is_string($configured) && $configured !== '' ? $configured : __DIR__ . '/data';
}

function createSchema(SQLite3 $db): void
{
    $statements = [
        'CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            password TEXT NOT NULL
        )',
        'CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL
        )',
        'CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )',
        'CREATE TABLE IF NOT EXISTS template (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            revision INTEGER NOT NULL,
            styles TEXT NOT NULL,
            placements TEXT NOT NULL
        )',
        'CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            data BLOB NOT NULL,
            sha256 TEXT NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL
        )',
        'CREATE TABLE IF NOT EXISTS documents (
            filename TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            data BLOB NOT NULL,
            bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            revision INTEGER NOT NULL
        )',
        'CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id TEXT NOT NULL,
            type TEXT NOT NULL,
            target TEXT NOT NULL,
            revision INTEGER NOT NULL,
            timestamp INTEGER NOT NULL
        )',
    ];
    foreach ($statements as $statement) {
        $db->exec($statement);
    }
}

function database(): SQLite3
{
    $path = directory();
    if (!is_dir($path) && !mkdir($path, 0700, true) && !is_dir($path)) {
        throw new RuntimeException('Cannot create data directory');
    }
    $databaseFile = $path . '/application.sqlite';
    $needsSchema = !is_file($databaseFile);
    $db = new SQLite3($databaseFile);
    $db->enableExceptions(true);
    $db->busyTimeout(10000);
    $db->exec('PRAGMA foreign_keys = ON');
    if ($needsSchema) {
        createSchema($db);
    }
    return $db;
}

function query(SQLite3 $db, string $sql, array $values = []): SQLite3Result
{
    $statement = $db->prepare($sql);
    foreach ($values as $name => $value) {
        $type = is_int($value)
            ? SQLITE3_INTEGER
            : ($value === null ? SQLITE3_NULL : SQLITE3_TEXT);
        $statement->bindValue(':' . $name, $value, $type);
    }
    return $statement->execute();
}

function rows(SQLite3 $db, string $sql, array $values = []): array
{
    $result = query($db, $sql, $values);
    $output = [];
    while (($value = $result->fetchArray(SQLITE3_ASSOC)) !== false) {
        $output[] = $value;
    }
    return $output;
}

function row(SQLite3 $db, string $sql, array $values = []): ?array
{
    $found = rows($db, $sql, $values);
    return $found[0] ?? null;
}

function encode(mixed $value): string
{
    return json_encode($value, JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}

function defaults(): array
{
    return [
        'color' => '#000000',
        'background' => null,
        'font_size' => 10,
        'weight' => 'normal',
        'border' => false,
        'visible' => true,
    ];
}

function initDatabase(bool $reset): void
{
    $path = directory() . '/application.sqlite';
    if ($reset && is_file($path)) {
        if (!unlink($path)) {
            throw new RuntimeException('Cannot reset application database');
        }
    }

    $db = database();
    // init.php is also the maintenance entry point for an older selected
    // database, so make sure all equivalent starter tables exist here.
    createSchema($db);
    foreach (['admin-a' => 'admin', 'admin-b' => 'admin', 'editor-a' => 'editor'] as $id => $role) {
        query($db, 'INSERT OR IGNORE INTO accounts(id, role, password)
                    VALUES(:id, :role, :password)', [
            'id' => $id,
            'role' => $role,
            'password' => password_hash('demo-pass', PASSWORD_BCRYPT),
        ]);
    }

    $styles = [];
    foreach (FIELDS as $field) {
        $styles[$field] = defaults();
    }
    query($db, 'INSERT OR IGNORE INTO template(id, revision, styles, placements)
                VALUES(1, 0, :styles, :placements)', [
        'styles' => encode($styles),
        'placements' => encode(array_fill_keys(SLOTS, null)),
    ]);

    $fixture = json_decode(
        file_get_contents(__DIR__ . '/fixtures/demo.json'),
        true,
        flags: JSON_THROW_ON_ERROR
    );
    foreach ($fixture as $profile) {
        query($db, 'INSERT OR IGNORE INTO profiles(id, data) VALUES(:id, :data)', [
            'id' => $profile['id'],
            'data' => encode($profile['values']),
        ]);
    }
}

/** Return the persisted template in the public response shape. */
function templateState(SQLite3 $db): array
{
    $template = row($db, 'SELECT revision, styles, placements FROM template WHERE id = 1');
    if ($template === null) {
        throw new RuntimeException('Template is not initialized');
    }

    $storedStyles = json_decode($template['styles'], true);
    $styles = [];
    foreach (FIELDS as $field) {
        $style = defaults();
        if (is_array($storedStyles) && isset($storedStyles[$field]) && is_array($storedStyles[$field])) {
            $style = array_replace($style, $storedStyles[$field]);
        }
        $styles[$field] = $style;
    }

    $storedPlacements = json_decode($template['placements'], true);
    $placements = array_fill_keys(SLOTS, null);
    if (is_array($storedPlacements)) {
        foreach (SLOTS as $slot) {
            if (array_key_exists($slot, $storedPlacements)) {
                $placements[$slot] = $storedPlacements[$slot];
            }
        }
    }

    return [
        'revision' => (int) $template['revision'],
        'styles' => $styles,
        'placements' => $placements,
    ];
}

function saveTemplate(SQLite3 $db, array $template): void
{
    query($db, 'UPDATE template
                SET revision = :revision, styles = :styles, placements = :placements
                WHERE id = 1', [
        'revision' => (int) $template['revision'],
        'styles' => encode($template['styles']),
        'placements' => encode($template['placements']),
    ]);
}

/** BEGIN IMMEDIATE serializes template/document/audit publications. */
function transaction(SQLite3 $db, callable $action): mixed
{
    $db->exec('BEGIN IMMEDIATE');
    try {
        $result = $action();
        $db->exec('COMMIT');
        return $result;
    } catch (Throwable $exception) {
        try {
            $db->exec('ROLLBACK');
        } catch (Throwable) {
            // Preserve the original operation error.
        }
        throw $exception;
    }
}

function audit(SQLite3 $db, array $actor, string $type, string $target, int $revision): void
{
    query($db, 'INSERT INTO audit(actor_id, type, target, revision, timestamp)
                VALUES(:actor_id, :type, :target, :revision, :timestamp)', [
        'actor_id' => $actor['id'],
        'type' => $type,
        'target' => $target,
        'revision' => $revision,
        'timestamp' => time(),
    ]);
}

function supportedRanges(): array
{
    static $ranges;
    if ($ranges === null) {
        $source = file_get_contents(__DIR__ . '/fixtures/supported_codepoints.json');
        if ($source === false) {
            throw new RuntimeException('Supported character data is unavailable');
        }
        $decoded = json_decode($source, true, flags: JSON_THROW_ON_ERROR);
        $ranges = is_array($decoded['ranges'] ?? null) ? $decoded['ranges'] : [];
    }
    return $ranges;
}

function validatedProfile(mixed $values): array
{
    if (!is_array($values)
        || array_diff(FIELDS, array_keys($values))
        || array_diff(array_keys($values), FIELDS)
        || count($values) !== count(FIELDS)) {
        fail(400, 'invalid_profile', 'A profile must contain exactly the six required fields.');
    }

    $ranges = supportedRanges();
    foreach (FIELDS as $field) {
        $value = $values[$field];
        if (!is_string($value)
            || !mb_check_encoding($value, 'UTF-8')
            || strlen($value) === 0
            || strlen($value) > 160
            || preg_match('/^\s*$/u', $value) === 1) {
            fail(400, 'invalid_profile', 'Profile values must be nonempty supported text.');
        }

        foreach (mb_str_split($value) as $character) {
            // Cc/Cf controls and line separators are not printable document
            // content, even if a font happens to contain a glyph for them.
            if (preg_match('/^[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]$/u', $character) === 1) {
                fail(400, 'invalid_profile', 'Profile values cannot contain control characters.');
            }
            $codepoint = mb_ord($character, 'UTF-8');
            $supported = false;
            foreach ($ranges as $range) {
                if (is_array($range) && count($range) >= 2
                    && $codepoint >= (int) $range[0]
                    && $codepoint <= (int) $range[1]) {
                    $supported = true;
                    break;
                }
            }
            if (!$supported) {
                fail(400, 'invalid_profile', 'Use characters supported by the supplied bilingual document fonts.');
            }
        }
    }

    // Rebuild in the contract order, retaining every accepted string verbatim.
    $result = [];
    foreach (FIELDS as $field) {
        $result[$field] = $values[$field];
    }
    return $result;
}
