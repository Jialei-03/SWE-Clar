<?php
$id=$_GET['page'] ?? 'home';
if (!is_string($id) || !preg_match('/^[A-Za-z0-9_-]+$/D',$id)) {http_response_code(400);exit('Invalid page');}
$path=(getenv('DATA_ROOT') ?: __DIR__.'/data').'/'.$id.'.json';
if(!is_file($path)){http_response_code(404);exit('Page not found');}
$page=json_decode(file_get_contents($path),true);$seo=[];
function e($value){return htmlspecialchars($value,ENT_QUOTES|ENT_SUBSTITUTE,'UTF-8');}
?><!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title><?=e($seo['title'] ?? $page['title'])?></title>
<?php if($seo): ?><meta name="description" content="<?=e($seo['description'])?>"><link rel="canonical" href="<?=e($seo['canonical_path'])?>"><meta name="robots" content="index,follow"><?php endif; ?>
<link rel="stylesheet" href="style.css"></head><body><main>
<header><p class="eyebrow">Sample resource site</p><h1><?=e($page['title'])?></h1></header>
<p class="intro"><?=e($page['body'])?></p>
<div class="assets"><?php foreach($page['images'] as $image): ?><img alt="<?=e($image['id'])?>" src="<?=e($image['data'])?>"><?php endforeach; ?></div>
<div class="sections"><?php foreach($page['sections'] as $index=>$section): ?><section><span><?=($index+1)?></span><h2><?=e($section)?></h2></section><?php endforeach; ?></div>
</main></body></html>
