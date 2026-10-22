<?php

$path = parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH);
if (!is_string($path) || !str_starts_with($path, '/api/')) {
    return false;
}

header('Content-Type: application/json; charset=utf-8');

function reply(int $status, array $value): never
{
    http_response_code($status);
    echo json_encode($value, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    exit;
}

try {
    $configPath = getenv('INSPECTION_CONFIG');
    if (!is_string($configPath) || trim($configPath) === '') {
        throw new RuntimeException('INSPECTION_CONFIG is not configured');
    }
    $config = json_decode(
        file_get_contents($configPath),
        true,
        512,
        JSON_THROW_ON_ERROR
    );
    if (!is_array($config)) {
        throw new RuntimeException('Invalid inspection configuration');
    }

    // Only this server-side mapping determines the role.  The request body
    // is never used for authentication or authorization.
    $authorization = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    $role = null;
    if (is_string($authorization) && str_starts_with($authorization, 'Bearer ')) {
        $accessCode = substr($authorization, 7);
        $accessCodes = $config['access_codes'] ?? [];
        if (is_array($accessCodes) && $accessCode !== '' && array_key_exists($accessCode, $accessCodes)) {
            $candidateRole = $accessCodes[$accessCode];
            if (is_string($candidateRole)) {
                $role = $candidateRole;
            }
        }
    }
    if (!in_array($role, ['admin', 'inspector', 'office'], true)) {
        reply(401, ['error' => ['code' => 'unauthenticated']]);
    }

    require_once __DIR__ . '/InspectionService.php';
    $db = database($config);

    if ($path === '/api/context' && ($_SERVER['REQUEST_METHOD'] ?? '') === 'GET') {
        $communities = [];
        foreach ($db->query('SELECT id FROM communities ORDER BY id')->fetchAll() as $community) {
            $communities[$community['id']] = [];
        }
        foreach (
            $db->query(
                'SELECT community, street FROM streets ORDER BY community, street'
            )->fetchAll() as $street
        ) {
            $communities[$street['community']][] = $street['street'];
        }

        $inspections = $db->query(
            'SELECT id, community, street, residence, status ' .
            'FROM inspections ORDER BY id'
        )->fetchAll();
        reply(200, [
            'role' => $role,
            'communities' => $communities,
            'inspections' => $inspections,
        ]);
    }

    if ($path !== '/api/command' || ($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
        reply(404, ['error' => ['code' => 'not_found']]);
    }

    $decoded = json_decode(
        file_get_contents('php://input'),
        true,
        512,
        JSON_THROW_ON_ERROR
    );
    if (!is_array($decoded)) {
        reply(400, ['error' => ['code' => 'invalid_request']]);
    }

    // Serializing writers makes the duplicate lookup and insert one atomic
    // operation, including when competing PHP workers submit the same ID.
    $db->exec('BEGIN IMMEDIATE');
    $commandTransactionStarted = true;
    try {
        $result = command($db, $decoded, $role);
        if (array_key_exists('error', $result)) {
            $db->exec('ROLLBACK');
        } else {
            $db->exec('COMMIT');
        }
        $commandTransactionStarted = false;
    } catch (Throwable $exception) {
        if ($commandTransactionStarted) {
            try {
                $db->exec('ROLLBACK');
            } catch (Throwable) {
                // Preserve the original command/database error.
            }
        }
        throw $exception;
    }

    reply(array_key_exists('error', $result) ? 400 : 200, $result);
} catch (Throwable) {
    // Do not expose configuration, access codes, SQL, or filesystem details.
    reply(400, ['error' => ['code' => 'invalid_request']]);
}
