<?php

/**
 * Open the records database and seed it exactly once from the supplied fixture.
 *
 * The database is deliberately the source of truth after this initialization
 * step.  In particular, commands never trust address data supplied by a
 * caller without checking the streets table.
 */
function database(array $config): PDO
{
    $databasePath = getenv('INSPECTION_DB');
    if (!is_string($databasePath) || trim($databasePath) === '') {
        throw new RuntimeException('INSPECTION_DB is not configured');
    }

    $db = new PDO('sqlite:' . $databasePath);
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $db->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    $db->setAttribute(PDO::ATTR_EMULATE_PREPARES, false);
    $db->exec('PRAGMA foreign_keys = ON');
    $db->exec('PRAGMA busy_timeout = 5000');

    // Create the schema before the initialization transaction.  IF NOT
    // EXISTS makes this safe when several PHP workers receive their first
    // request at the same time.
    $db->exec(
        'CREATE TABLE IF NOT EXISTS communities (' .
        'id TEXT PRIMARY KEY NOT NULL' .
        ')'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS streets (' .
        'community TEXT NOT NULL,' .
        'street TEXT NOT NULL,' .
        'PRIMARY KEY (community, street),' .
        'FOREIGN KEY (community) REFERENCES communities(id)' .
        ')'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS inspections (' .
        'id TEXT PRIMARY KEY NOT NULL,' .
        'community TEXT NOT NULL,' .
        'street TEXT NOT NULL,' .
        'residence TEXT NOT NULL,' .
        'status TEXT NOT NULL CHECK (status IN ("open", "closed")),' .
        'FOREIGN KEY (community, street) REFERENCES streets(community, street)' .
        ')'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS initialized (' .
        'id INTEGER PRIMARY KEY' .
        ')'
    );
    $db->exec(
        'CREATE INDEX IF NOT EXISTS inspections_community_idx ' .
        'ON inspections(community)'
    );

    // BEGIN IMMEDIATE prevents two first requests from both observing an
    // empty initialization marker and trying to seed the same rows.
    $db->exec('BEGIN IMMEDIATE');
    $initializationStarted = true;
    try {
        $initialized = $db->query('SELECT 1 FROM initialized LIMIT 1')->fetchColumn();
        if ($initialized === false) {
            $communities = $config['communities'] ?? null;
            if (!is_array($communities)) {
                throw new RuntimeException('Invalid communities fixture');
            }

            $communityInsert = $db->prepare(
                'INSERT INTO communities (id) VALUES (?)'
            );
            $streetInsert = $db->prepare(
                'INSERT INTO streets (community, street) VALUES (?, ?)'
            );
            foreach ($communities as $community => $streets) {
                if (!is_string($community) || !is_array($streets)) {
                    throw new RuntimeException('Invalid communities fixture');
                }
                $communityInsert->execute([$community]);
                foreach ($streets as $street) {
                    if (!is_string($street)) {
                        throw new RuntimeException('Invalid streets fixture');
                    }
                    $streetInsert->execute([$community, $street]);
                }
            }

            $inspectionInsert = $db->prepare(
                'INSERT INTO inspections ' .
                '(id, community, street, residence, status) VALUES (?, ?, ?, ?, ?)'
            );
            $inspections = $config['inspections'] ?? [];
            if (!is_array($inspections)) {
                throw new RuntimeException('Invalid inspections fixture');
            }
            foreach ($inspections as $inspection) {
                if (!is_array($inspection)) {
                    throw new RuntimeException('Invalid inspections fixture');
                }
                foreach (['id', 'community', 'street', 'residence', 'status'] as $field) {
                    if (!array_key_exists($field, $inspection) || !is_string($inspection[$field])) {
                        throw new RuntimeException('Invalid inspections fixture');
                    }
                }
                $inspectionInsert->execute([
                    $inspection['id'],
                    $inspection['community'],
                    $inspection['street'],
                    $inspection['residence'],
                    $inspection['status'],
                ]);
            }

            $db->exec('INSERT INTO initialized (id) VALUES (1)');
        }
        $db->exec('COMMIT');
        $initializationStarted = false;
    } catch (Throwable $exception) {
        if ($initializationStarted) {
            try {
                $db->exec('ROLLBACK');
            } catch (Throwable) {
                // Preserve the original initialization error.
            }
        }
        throw $exception;
    }

    return $db;
}

function nonEmptyString(mixed $value): bool
{
    return is_string($value) && trim($value) !== '';
}

function operationError(string $code): array
{
    return ['error' => ['code' => $code]];
}

function isDuplicateInspectionError(PDOException $exception): bool
{
    $errorInfo = $exception->errorInfo;
    $message = strtolower($exception->getMessage());

    // The pre-insert lookup handles normal duplicates.  This branch handles
    // the small race window for callers using another connection and keeps a
    // uniqueness violation a structured operation error rather than a 500.
    return ($errorInfo[0] ?? null) === '23000'
        && (str_contains($message, 'unique') || str_contains($message, 'primary key'));
}

/**
 * Execute one authenticated operation.  The caller's role is supplied by
 * router.php from the access-code map; no role field in $input is consulted.
 */
function command(PDO $db, array $input, string $role): array
{
    $kind = $input['type'] ?? null;

    if ($kind === 'create') {
        if (!in_array($role, ['admin', 'inspector'], true)) {
            return operationError('forbidden');
        }

        foreach (['id', 'community', 'street', 'residence'] as $field) {
            if (!array_key_exists($field, $input) || !nonEmptyString($input[$field])) {
                return operationError('invalid_address');
            }
        }

        // Checking the composite address, rather than checking the street
        // name alone, prevents a street from being used in another community.
        $streetQuery = $db->prepare(
            'SELECT 1 FROM streets WHERE community = ? AND street = ? LIMIT 1'
        );
        $streetQuery->execute([$input['community'], $input['street']]);
        if ($streetQuery->fetchColumn() === false) {
            return operationError('invalid_address');
        }

        $existingQuery = $db->prepare(
            'SELECT 1 FROM inspections WHERE id = ? LIMIT 1'
        );
        $existingQuery->execute([$input['id']]);
        if ($existingQuery->fetchColumn() !== false) {
            return operationError('duplicate_id');
        }

        try {
            $insert = $db->prepare(
                'INSERT INTO inspections ' .
                '(id, community, street, residence, status) VALUES (?, ?, ?, ?, ?)'
            );
            $insert->execute([
                $input['id'],
                $input['community'],
                $input['street'],
                $input['residence'],
                'open',
            ]);
        } catch (PDOException $exception) {
            if (isDuplicateInspectionError($exception)) {
                return operationError('duplicate_id');
            }
            throw $exception;
        }

        return ['result' => ['id' => $input['id'], 'status' => 'open']];
    }

    if ($kind === 'delete') {
        if ($role !== 'admin') {
            return operationError('forbidden');
        }
        if (!array_key_exists('id', $input) || !nonEmptyString($input['id'])) {
            return operationError('not_found');
        }

        $lookup = $db->prepare(
            'SELECT status FROM inspections WHERE id = ? LIMIT 1'
        );
        $lookup->execute([$input['id']]);
        $inspection = $lookup->fetch();
        if ($inspection === false) {
            return operationError('not_found');
        }
        if ($inspection['status'] !== 'open') {
            return operationError('closed_inspection');
        }

        $delete = $db->prepare(
            'DELETE FROM inspections WHERE id = ? AND status = "open"'
        );
        $delete->execute([$input['id']]);
        if ($delete->rowCount() !== 1) {
            // A command transaction is serialized, so this is defensive; it
            // also guarantees that a surprising database state cannot report
            // success without changing exactly one open record.
            return operationError('not_found');
        }

        return ['result' => ['deleted' => true]];
    }

    if ($kind === 'report') {
        if (!array_key_exists('community', $input) || !nonEmptyString($input['community'])) {
            return operationError('unknown_community');
        }

        $communityQuery = $db->prepare(
            'SELECT 1 FROM communities WHERE id = ? LIMIT 1'
        );
        $communityQuery->execute([$input['community']]);
        if ($communityQuery->fetchColumn() === false) {
            return operationError('unknown_community');
        }

        $counts = $db->prepare(
            'SELECT COUNT(*) AS total,' .
            'COALESCE(SUM(CASE WHEN status = "open" THEN 1 ELSE 0 END), 0) AS open_count,' .
            'COALESCE(SUM(CASE WHEN status = "closed" THEN 1 ELSE 0 END), 0) AS closed_count ' .
            'FROM inspections WHERE community = ?'
        );
        $counts->execute([$input['community']]);
        $row = $counts->fetch();

        return [
            'result' => [
                'total' => (int) $row['total'],
                'by_status' => [
                    'open' => (int) $row['open_count'],
                    'closed' => (int) $row['closed_count'],
                ],
            ],
        ];
    }

    return operationError('unknown_command');
}
