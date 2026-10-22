<?php
$id = $_GET['page'] ?? 'home';
if (!is_string($id) || !preg_match('/^[A-Za-z0-9_-]+$/D', $id)) {
    http_response_code(400);
    exit('Invalid page');
}

$dataRoot = getenv('DATA_ROOT');
if (!is_string($dataRoot) || $dataRoot === '') {
    $dataRoot = __DIR__ . '/data';
}
$path = rtrim($dataRoot, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . $id . '.json';
if (!is_file($path)) {
    http_response_code(404);
    exit('Page not found');
}

$page = json_decode(file_get_contents($path), true);
if (!is_array($page)) {
    http_response_code(500);
    exit('Invalid page data');
}

function e($value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

$seo = isset($page['seo']) && is_array($page['seo']) ? $page['seo'] : [];
$title = array_key_exists('title', $page) ? $page['title'] : '';
$body = array_key_exists('body', $page) ? $page['body'] : '';
$sections = isset($page['sections']) && is_array($page['sections']) ? $page['sections'] : [];
$images = isset($page['images']) && is_array($page['images']) ? $page['images'] : [];
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title><?= e($seo['title'] ?? $title) ?></title>
<?php if ($seo): ?>
    <meta name="description" content="<?= e($seo['description'] ?? '') ?>">
    <link rel="canonical" href="<?= e($seo['canonical_path'] ?? '') ?>">
    <meta name="robots" content="<?= (($seo['indexable'] ?? false) === true) ? 'index,follow' : 'noindex,nofollow' ?>">
<?php endif; ?>
    <link rel="stylesheet" href="style.css">
</head>
<body>
<main>
    <header>
        <p class="eyebrow">Sample resource site</p>
        <h1><?= e($title) ?></h1>
    </header>
    <p class="intro"><?= e($body) ?></p>
    <div class="assets">
<?php foreach ($images as $image): ?>
        <?php if (is_array($image) && isset($image['data'])): ?>
        <img alt="<?= e($image['id'] ?? '') ?>" src="<?= e($image['data']) ?>">
        <?php endif; ?>
<?php endforeach; ?>
    </div>
    <div class="sections">
<?php foreach ($sections as $index => $section): ?>
        <section>
            <span><?= e($index + 1) ?></span>
            <h2><?= e($section) ?></h2>
        </section>
<?php endforeach; ?>
    </div>
</main>
</body>
</html>
