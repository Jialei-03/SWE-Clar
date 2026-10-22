<?php
declare(strict_types=1);

ini_set('display_errors', '0');
require __DIR__ . '/storage.php';
require __DIR__ . '/features.php';

function jsonResponse(mixed $data, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo encode($data);
    exit;
}

function bodyValueToArray(mixed $value): mixed
{
    if ($value instanceof stdClass) {
        $output = [];
        foreach (get_object_vars($value) as $key => $nested) {
            $output[$key] = bodyValueToArray($nested);
        }
        return $output;
    }
    if (is_array($value)) {
        foreach ($value as $key => $nested) {
            $value[$key] = bodyValueToArray($nested);
        }
    }
    return $value;
}

function body(string $unicodeErrorCode = 'invalid_json'): array
{
    $raw = file_get_contents('php://input');
    if ($raw === false) {
        fail(400, 'invalid_json', 'The request body is not valid JSON.');
    }
    try {
        $decoded = json_decode($raw, false, flags: JSON_THROW_ON_ERROR);
        if (!is_object($decoded)) {
            fail(400, 'invalid_json', 'The request body must be a JSON object.');
        }
        // Convert only objects, without a JSON round trip that would turn
        // 10.0 into an integer and defeat strict integer validation.
        return bodyValueToArray($decoded);
    } catch (JsonException $exception) {
        if ($unicodeErrorCode !== 'invalid_json'
            && in_array($exception->getCode(), [JSON_ERROR_UTF8, JSON_ERROR_UTF16], true)) {
            fail(400, $unicodeErrorCode, 'Profile values must be valid UTF-8 text.');
        }
        fail(400, 'invalid_json', 'The request body is not valid JSON.');
    }
}

function actor(SQLite3 $db): array
{
    $token = $_COOKIE['document_session'] ?? '';
    if (!is_string($token) || $token === '') {
        fail(401, 'authentication_required', 'An active session is required.');
    }
    $user = row(
        $db,
        'SELECT a.id, a.role
         FROM sessions s JOIN accounts a ON a.id = s.actor_id
         WHERE s.token = :token',
        ['token' => $token]
    );
    if ($user === null) {
        fail(401, 'authentication_required', 'An active session is required.');
    }
    return ['id' => (string) $user['id'], 'role' => (string) $user['role']];
}

function publicAssets(SQLite3 $db): array
{
    return array_map(static fn(array $asset): array => [
        'id' => (string) $asset['id'],
        'sha256' => (string) $asset['sha256'],
        'width' => (int) $asset['width'],
        'height' => (int) $asset['height'],
    ], rows($db, 'SELECT id, sha256, width, height FROM assets ORDER BY id'));
}

function publicDocuments(SQLite3 $db): array
{
    return array_map(static fn(array $document): array => [
        'filename' => (string) $document['filename'],
        'kind' => (string) $document['kind'],
        'profile_id' => (string) $document['profile_id'],
        'bytes' => (int) $document['bytes'],
        'sha256' => (string) $document['sha256'],
        'revision' => (int) $document['revision'],
    ], rows($db, 'SELECT filename, kind, profile_id, bytes, sha256, revision
                   FROM documents ORDER BY filename'));
}

function publicAudit(SQLite3 $db): array
{
    return array_map(static fn(array $event): array => [
        'id' => (int) $event['id'],
        'actor_id' => (string) $event['actor_id'],
        'type' => (string) $event['type'],
        'target' => (string) $event['target'],
        'revision' => (int) $event['revision'],
        'timestamp' => (int) $event['timestamp'],
    ], rows($db, 'SELECT id, actor_id, type, target, revision, timestamp
                   FROM audit ORDER BY id'));
}

try {
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
    if (!is_string($path)) {
        fail(404, 'not_found');
    }

    $static = [
        '/' => ['web/index.html', 'text/html; charset=utf-8'],
        '/ui.js' => ['web/ui.js', 'text/javascript; charset=utf-8'],
        '/style.css' => ['web/style.css', 'text/css; charset=utf-8'],
    ];
    if ($method === 'GET' && isset($static[$path])) {
        header('Content-Type: ' . $static[$path][1]);
        header('Cache-Control: no-store');
        readfile(__DIR__ . '/' . $static[$path][0]);
        exit;
    }

    if (!str_starts_with($path, '/api/')) {
        fail(404, 'not_found');
    }

    $db = database();
    if ($path === '/api/login' && $method === 'POST') {
        $request = body();
        $username = $request['username'] ?? null;
        $password = $request['password'] ?? null;
        $user = is_string($username)
            ? row($db, 'SELECT id, role, password FROM accounts WHERE id = :id', ['id' => $username])
            : null;
        if ($user === null || !is_string($password) || !password_verify($password, $user['password'])) {
            fail(401, 'invalid_credentials', 'The username or password is incorrect.');
        }

        $token = bin2hex(random_bytes(32));
        query($db, 'INSERT INTO sessions(token, actor_id) VALUES(:token, :actor_id)', [
            'token' => $token,
            'actor_id' => $user['id'],
        ]);
        setcookie('document_session', $token, [
            'path' => '/',
            'httponly' => true,
            'samesite' => 'Strict',
        ]);
        jsonResponse(['user' => ['id' => (string) $user['id'], 'role' => (string) $user['role']]]);
    }

    $who = actor($db);
    if ($path === '/api/session' && $method === 'GET') {
        jsonResponse(['user' => $who]);
    }
    if ($path === '/api/logout' && $method === 'POST') {
        body();
        $token = $_COOKIE['document_session'] ?? '';
        if (is_string($token) && $token !== '') {
            query($db, 'DELETE FROM sessions WHERE token = :token', ['token' => $token]);
        }
        setcookie('document_session', '', [
            'expires' => 1,
            'path' => '/',
            'httponly' => true,
            'samesite' => 'Strict',
        ]);
        jsonResponse(['ok' => true]);
    }

    if ($path === '/api/profiles' && $method === 'GET') {
        $profiles = array_map(static fn(array $profile): array => [
            'id' => (string) $profile['id'],
            'values' => json_decode($profile['data'], true),
        ], rows($db, 'SELECT id, data FROM profiles ORDER BY id'));
        jsonResponse(['profiles' => $profiles]);
    }
    if ($path === '/api/profiles' && $method === 'POST') {
        $request = body('invalid_profile');
        $id = $request['id'] ?? null;
        $values = validatedProfile($request['values'] ?? null);
        if (!is_string($id) || preg_match('/\A[a-z][a-z0-9-]{0,39}\z/D', $id) !== 1) {
            fail(400, 'invalid_profile', 'The profile id is invalid.');
        }
        transaction($db, function () use ($db, $id, $values): void {
            if (row($db, 'SELECT id FROM profiles WHERE id = :id', ['id' => $id]) !== null) {
                fail(409, 'profile_exists', 'That profile already exists.');
            }
            query($db, 'INSERT INTO profiles(id, data) VALUES(:id, :data)', [
                'id' => $id,
                'data' => encode($values),
            ]);
        });
        jsonResponse(['profile' => ['id' => $id, 'values' => $values]], 201);
    }
    if (preg_match('/\A\/api\/profiles\/([a-z][a-z0-9-]{0,39})\z/D', $path, $match) === 1
        && $method === 'PUT') {
        $request = body('invalid_profile');
        $values = validatedProfile($request['values'] ?? null);
        $id = $match[1];
        transaction($db, function () use ($db, $id, $values): void {
            if (row($db, 'SELECT id FROM profiles WHERE id = :id', ['id' => $id]) === null) {
                fail(404, 'not_found', 'Profile not found.');
            }
            query($db, 'UPDATE profiles SET data = :data WHERE id = :id', [
                'id' => $id,
                'data' => encode($values),
            ]);
        });
        jsonResponse(['profile' => ['id' => $id, 'values' => $values]]);
    }

    if ($path === '/api/template' && $method === 'GET') {
        jsonResponse(templateState($db));
    }
    if (preg_match('/\A\/api\/template\/fields\/([^\/]+)\z/D', $path, $match) === 1
        && $method === 'PATCH') {
        admin($who);
        jsonResponse(configureField($db, $who, $match[1], body()));
    }
    if ($path === '/api/assets' && $method === 'POST') {
        jsonResponse(uploadAsset($db, $who), 201);
    }
    if ($path === '/api/assets' && $method === 'GET') {
        jsonResponse(['assets' => publicAssets($db)]);
    }
    if (preg_match('/\A\/api\/assets\/([a-f0-9]{32})\z/D', $path, $match) === 1
        && $method === 'GET') {
        $asset = row($db, 'SELECT data FROM assets WHERE id = :id', ['id' => $match[1]]);
        if ($asset === null || !is_string($asset['data'])) {
            fail(404, 'not_found', 'Asset not found.');
        }
        header('Content-Type: image/png');
        header('Cache-Control: no-store');
        header('Content-Length: ' . strlen($asset['data']));
        echo $asset['data'];
        exit;
    }
    if (preg_match('/\A\/api\/template\/placements\/([^\/]+)\z/D', $path, $match) === 1
        && $method === 'PUT') {
        admin($who);
        jsonResponse(placeAsset($db, $who, $match[1], body()));
    }

    if ($path === '/api/render' && $method === 'POST') {
        jsonResponse(renderDocument($db, $who, body()), 201);
    }
    if ($path === '/api/documents' && $method === 'GET') {
        jsonResponse(['documents' => publicDocuments($db)]);
    }
    if (preg_match('/\A\/api\/documents\/([A-Za-z0-9_-]{1,64}\.pdf)\z/D', $path, $match) === 1
        && $method === 'GET') {
        $document = row($db, 'SELECT data FROM documents WHERE filename = :filename', ['filename' => $match[1]]);
        if ($document === null || !is_string($document['data'])) {
            fail(404, 'not_found', 'Document not found.');
        }
        header('Content-Type: application/pdf');
        header('Content-Disposition: attachment; filename="' . $match[1] . '"');
        header('Content-Length: ' . strlen($document['data']));
        header('Cache-Control: no-store');
        echo $document['data'];
        exit;
    }
    if ($path === '/api/audit' && $method === 'GET') {
        jsonResponse(['events' => publicAudit($db)]);
    }

    fail(404, 'not_found');
} catch (ApiError $exception) {
    jsonResponse([
        'error' => [
            'code' => $exception->kind,
            'message' => $exception->getMessage(),
        ],
    ], $exception->status);
} catch (Throwable $exception) {
    error_log($exception->getMessage());
    $renderFailure = ($method ?? '') === 'POST' && ($path ?? '') === '/api/render';
    jsonResponse([
        'error' => [
            'code' => $renderFailure ? 'render_failed' : 'internal_error',
            'message' => $renderFailure
                ? 'The document could not be published.'
                : 'The operation could not be completed.',
        ],
    ], 500);
}
