<?php
declare(strict_types=1);

require_once __DIR__ . '/document.php';

function admin(array $actor): void
{
    if (($actor['role'] ?? null) !== 'admin') {
        fail(403, 'configuration_denied', 'Only authenticated administrators can change document configuration.');
    }
}

function expectedRevision(array $request): int
{
    if (!array_key_exists('expected_revision', $request)
        || !is_int($request['expected_revision'])
        || $request['expected_revision'] < 0) {
        fail(400, 'invalid_revision', 'expected_revision must be a nonnegative integer.');
    }
    return $request['expected_revision'];
}

function stylePatch(mixed $values): array
{
    if (!is_array($values) || count($values) === 0) {
        fail(400, 'invalid_style', 'values must be a nonempty style patch.');
    }

    $allowed = ['color', 'background', 'font_size', 'weight', 'border', 'visible'];
    if (array_diff(array_keys($values), $allowed)) {
        fail(400, 'invalid_style', 'The style patch contains an unknown property.');
    }

    $patch = [];
    foreach ($values as $key => $value) {
        switch ($key) {
            case 'color':
                if (!is_string($value) || preg_match('/\A#[0-9a-fA-F]{6}\z/D', $value) !== 1) {
                    fail(400, 'invalid_style', 'color must be a six-digit hexadecimal color.');
                }
                $patch[$key] = strtoupper($value);
                break;
            case 'background':
                if ($value !== null
                    && (!is_string($value) || preg_match('/\A#[0-9a-fA-F]{6}\z/D', $value) !== 1)) {
                    fail(400, 'invalid_style', 'background must be a color or null.');
                }
                $patch[$key] = $value === null ? null : strtoupper($value);
                break;
            case 'font_size':
                if (!is_int($value) || $value < 6 || $value > 12) {
                    fail(400, 'invalid_style', 'font_size must be an integer from 6 through 12.');
                }
                $patch[$key] = $value;
                break;
            case 'weight':
                if (!is_string($value) || !in_array($value, ['normal', 'bold'], true)) {
                    fail(400, 'invalid_style', 'weight must be normal or bold.');
                }
                $patch[$key] = $value;
                break;
            case 'border':
            case 'visible':
                if (!is_bool($value)) {
                    fail(400, 'invalid_style', $key . ' must be boolean.');
                }
                $patch[$key] = $value;
                break;
            default:
                // The key whitelist above makes this unreachable.
                fail(400, 'invalid_style');
        }
    }
    return $patch;
}

function configureField(SQLite3 $db, array $actor, string $field, array $request): array
{
    admin($actor);
    if (!in_array($field, FIELDS, true)) {
        fail(400, 'invalid_style', 'Unknown template field.');
    }
    $revision = expectedRevision($request);
    $patch = stylePatch($request['values'] ?? null);

    return transaction($db, function () use ($db, $actor, $field, $revision, $patch): array {
        $template = templateState($db);
        if ($template['revision'] !== $revision) {
            fail(409, 'revision_conflict', 'The template changed; refresh and retry explicitly.');
        }

        $merged = array_replace($template['styles'][$field], $patch);
        if ($merged === $template['styles'][$field]) {
            return $template;
        }

        $template['styles'][$field] = $merged;
        $template['revision']++;
        saveTemplate($db, $template);
        audit($db, $actor, 'configure_field', $field, $template['revision']);
        return templateState($db);
    });
}

/** Decode and independently inspect a PNG; return dimensions or null. */
function inspectPng(string $data): ?array
{
    if ($data === '' || strlen($data) > 262144) {
        return null;
    }
    $info = @getimagesizefromstring($data);
    if ($info === false || ($info[2] ?? null) !== IMAGETYPE_PNG) {
        return null;
    }
    // Reject dimensions from the PNG header before asking GD to allocate an
    // image, which also makes oversized dimension fixtures safe to inspect.
    $headerWidth = (int) ($info[0] ?? 0);
    $headerHeight = (int) ($info[1] ?? 0);
    if ($headerWidth < 8 || $headerWidth > 1024 || $headerHeight < 8 || $headerHeight > 1024) {
        return null;
    }
    $decoded = @imagecreatefromstring($data);
    if ($decoded === false) {
        return null;
    }
    $width = imagesx($decoded);
    $height = imagesy($decoded);
    imagedestroy($decoded);
    if ($width !== $headerWidth || $height !== $headerHeight) {
        return null;
    }
    return ['width' => $width, 'height' => $height];
}

function uploadAsset(SQLite3 $db, array $actor): array
{
    // Check trust before looking at multipart content: an editor gets the
    // policy error, not a validation hint about an otherwise forbidden action.
    admin($actor);
    $upload = $_FILES['image'] ?? null;
    if (!is_array($upload)
        || !array_key_exists('name', $upload)
        || is_array($upload['name'])
        || ($upload['error'] ?? null) !== UPLOAD_ERR_OK
        || !is_string($upload['tmp_name'] ?? null)
        || $upload['tmp_name'] === '') {
        fail(400, 'invalid_asset', 'A single PNG image upload is required.');
    }

    $data = @file_get_contents($upload['tmp_name']);
    if ($data === false || strlen($data) > 262144) {
        fail(400, 'invalid_asset', 'The uploaded image is invalid or too large.');
    }
    $dimensions = inspectPng($data);
    if ($dimensions === null) {
        fail(400, 'invalid_asset', 'The upload must be a genuine PNG between 8 and 1024 pixels per side.');
    }

    $sha256 = hash('sha256', $data);
    return transaction($db, function () use ($db, $actor, $data, $dimensions, $sha256): array {
        do {
            $id = bin2hex(random_bytes(16));
        } while (row($db, 'SELECT id FROM assets WHERE id = :id', ['id' => $id]) !== null);

        $statement = $db->prepare('INSERT INTO assets(id, data, sha256, width, height)
                                   VALUES(:id, :data, :sha256, :width, :height)');
        $statement->bindValue(':id', $id, SQLITE3_TEXT);
        $statement->bindValue(':data', $data, SQLITE3_BLOB);
        $statement->bindValue(':sha256', $sha256, SQLITE3_TEXT);
        $statement->bindValue(':width', $dimensions['width'], SQLITE3_INTEGER);
        $statement->bindValue(':height', $dimensions['height'], SQLITE3_INTEGER);
        $statement->execute();

        $template = templateState($db);
        audit($db, $actor, 'upload_asset', $id, $template['revision']);
        return [
            'asset' => [
                'id' => $id,
                'sha256' => $sha256,
                'width' => $dimensions['width'],
                'height' => $dimensions['height'],
            ],
        ];
    });
}

function placeAsset(SQLite3 $db, array $actor, string $slot, array $request): array
{
    admin($actor);
    if (!in_array($slot, SLOTS, true)) {
        fail(400, 'invalid_asset', 'Unknown image placement slot.');
    }
    $revision = expectedRevision($request);
    if (!array_key_exists('asset_id', $request)
        || ($request['asset_id'] !== null && !is_string($request['asset_id']))) {
        fail(400, 'invalid_asset', 'asset_id must be a stored asset id or null.');
    }
    $assetId = $request['asset_id'];
    if (is_string($assetId) && $assetId === '') {
        fail(400, 'invalid_asset', 'asset_id must be a stored asset id or null.');
    }

    return transaction($db, function () use ($db, $actor, $slot, $revision, $assetId): array {
        $template = templateState($db);
        if ($template['revision'] !== $revision) {
            fail(409, 'revision_conflict', 'The template changed; refresh and retry explicitly.');
        }
        if ($assetId !== null && row($db, 'SELECT id FROM assets WHERE id = :id', ['id' => $assetId]) === null) {
            fail(400, 'invalid_asset', 'The selected image is not stored.');
        }

        if ($template['placements'][$slot] === $assetId) {
            return $template;
        }

        $template['placements'][$slot] = $assetId;
        $template['revision']++;
        saveTemplate($db, $template);
        audit($db, $actor, 'place_asset', $slot, $template['revision']);
        return templateState($db);
    });
}

function assertRenderableTemplate(array $template): void
{
    foreach (FIELDS as $field) {
        $style = $template['styles'][$field] ?? null;
        if (!is_array($style)
            || !is_string($style['color'] ?? null)
            || preg_match('/\A#[0-9A-Fa-f]{6}\z/D', $style['color']) !== 1
            || (($style['background'] ?? null) !== null
                && (!is_string($style['background'])
                    || preg_match('/\A#[0-9A-Fa-f]{6}\z/D', $style['background']) !== 1))
            || !is_int($style['font_size'] ?? null)
            || $style['font_size'] < 6
            || $style['font_size'] > 12
            || !is_string($style['weight'] ?? null)
            || !in_array($style['weight'], ['normal', 'bold'], true)
            || !is_bool($style['border'] ?? null)
            || !is_bool($style['visible'] ?? null)) {
            throw new RuntimeException('The stored template is invalid');
        }
    }
}

/** Load and verify only assets that the selected document kind will embed. */
function renderAssets(SQLite3 $db, array $template, string $kind): array
{
    $slots = ['front_left', 'front_right', 'back'];
    if ($kind === 'sample_pass') {
        $slots[] = 'watermark';
    }

    $assets = [];
    foreach ($slots as $slot) {
        $assetId = $template['placements'][$slot] ?? null;
        if ($assetId === null) {
            continue;
        }
        if (!is_string($assetId) || $assetId === '') {
            fail(422, 'asset_unavailable', 'A configured image is unavailable.');
        }
        if (isset($assets[$assetId])) {
            continue;
        }
        $stored = row($db, 'SELECT id, data, sha256, width, height FROM assets WHERE id = :id', ['id' => $assetId]);
        if ($stored === null || !is_string($stored['data']) || !is_string($stored['sha256'])) {
            fail(422, 'asset_unavailable', 'A configured image is unavailable.');
        }
        if (!hash_equals($stored['sha256'], hash('sha256', $stored['data']))) {
            fail(422, 'asset_unavailable', 'A configured image is corrupt.');
        }
        $dimensions = inspectPng($stored['data']);
        if ($dimensions === null
            || (int) $stored['width'] !== $dimensions['width']
            || (int) $stored['height'] !== $dimensions['height']) {
            fail(422, 'asset_unavailable', 'A configured image is corrupt.');
        }
        $stored['width'] = $dimensions['width'];
        $stored['height'] = $dimensions['height'];
        $assets[$assetId] = $stored;
    }
    return $assets;
}

function validPdfOutput(string $pdf): bool
{
    if (!str_starts_with($pdf, '%PDF-') || !str_contains($pdf, '%%EOF')) {
        return false;
    }
    preg_match_all('/\/Type\s*\/Page\b/', $pdf, $pages);
    return count($pages[0]) === 2;
}

function renderDocument(SQLite3 $db, array $actor, array $request): array
{
    $kind = $request['kind'] ?? null;
    $filename = $request['filename'] ?? null;
    $profileId = $request['profile_id'] ?? null;
    if (!is_string($kind)
        || !in_array($kind, ['sample_card', 'sample_pass'], true)
        || !is_string($filename)
        || preg_match('/\A[A-Za-z0-9_-]{1,64}\.pdf\z/D', $filename) !== 1
        || !is_string($profileId)
        || preg_match('/\A[a-z][a-z0-9-]{0,39}\z/D', $profileId) !== 1) {
        fail(400, 'invalid_request', 'The document kind, filename, or profile is invalid.');
    }

    try {
        return transaction($db, function () use ($db, $actor, $kind, $filename, $profileId): array {
            $storedProfile = row($db, 'SELECT data FROM profiles WHERE id = :id', ['id' => $profileId]);
            if ($storedProfile === null) {
                fail(404, 'not_found', 'Profile not found.');
            }
            try {
                $decoded = json_decode($storedProfile['data'], true, flags: JSON_THROW_ON_ERROR);
            } catch (JsonException) {
                fail(400, 'invalid_profile', 'The selected profile is invalid.');
            }
            $values = validatedProfile($decoded);
            $template = templateState($db);
            assertRenderableTemplate($template);
            $assets = renderAssets($db, $template, $kind);

            try {
                $pdf = renderPDF($values, $template, $assets, $kind);
            } catch (ApiError $exception) {
                throw $exception;
            } catch (Throwable $exception) {
                error_log('PDF generation failed: ' . $exception->getMessage());
                fail(500, 'render_failed', 'The PDF could not be generated.');
            }
            if (!validPdfOutput($pdf)) {
                fail(500, 'render_failed', 'The generated PDF failed output validation.');
            }

            $sha256 = hash('sha256', $pdf);
            $bytes = strlen($pdf);
            $statement = $db->prepare('INSERT INTO documents(filename, kind, profile_id, data, bytes, sha256, revision)
                                       VALUES(:filename, :kind, :profile_id, :data, :bytes, :sha256, :revision)
                                       ON CONFLICT(filename) DO UPDATE SET
                                         kind = excluded.kind,
                                         profile_id = excluded.profile_id,
                                         data = excluded.data,
                                         bytes = excluded.bytes,
                                         sha256 = excluded.sha256,
                                         revision = excluded.revision');
            $statement->bindValue(':filename', $filename, SQLITE3_TEXT);
            $statement->bindValue(':kind', $kind, SQLITE3_TEXT);
            $statement->bindValue(':profile_id', $profileId, SQLITE3_TEXT);
            $statement->bindValue(':data', $pdf, SQLITE3_BLOB);
            $statement->bindValue(':bytes', $bytes, SQLITE3_INTEGER);
            $statement->bindValue(':sha256', $sha256, SQLITE3_TEXT);
            $statement->bindValue(':revision', $template['revision'], SQLITE3_INTEGER);
            $statement->execute();

            audit($db, $actor, 'render', $filename, $template['revision']);
            return [
                'document' => [
                    'filename' => $filename,
                    'kind' => $kind,
                    'profile_id' => $profileId,
                    'bytes' => $bytes,
                    'sha256' => $sha256,
                    'revision' => $template['revision'],
                ],
            ];
        });
    } catch (ApiError $exception) {
        throw $exception;
    } catch (Throwable $exception) {
        error_log('Document publication failed: ' . $exception->getMessage());
        fail(500, 'render_failed', 'The document could not be published.');
    }
}
