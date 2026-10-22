<?php
/**
 * Plugin Name: Synthetic Directory Component
 * Description: Independently reconstructed directory rendering, cache and asset component.
 * Version: 1.0.0
 */
if (!defined('ABSPATH')) { exit; }

function directory_normalize_member(array $raw): array {
    return ['id'=>(string)$raw['id'], 'name'=>(string)$raw['name'], 'group_code'=>$raw['group_code'] ?? null, 'activity_count'=>$raw['activity_count'] ?? 0];
}

function directory_markup(string $page, array $members): string {
    update_option('directory_render_count', (int)get_option('directory_render_count', 0) + 1, false);
    if ($page === 'about') { return '<h1>About this directory</h1><p>An independent example directory with synthetic records.</p>'; }
    $html = '<h1>Member directory</h1><form id="filter-form"><label>Find a member <input id="filter" type="search"></label><button>Filter</button></form><div id="members">';
    foreach ($members as $raw) {
        $m = directory_normalize_member($raw);
        $html .= '<article data-member="'.esc_attr($m['id']).'"><h2>'.esc_html($m['name']).'</h2><p>Group code: <span class="group_code">'.esc_html($m['group_code'] ?? 'Unavailable').'</span></p><p>Activities: <span class="activity_count">'.esc_html($m['activity_count'] === null ? 'Unavailable' : (string)$m['activity_count']).'</span></p></article>';
    }
    return $html.'</div><p id="filter-status" role="status"></p>';
}

function directory_content(string $page): string {
    $members = get_option('directory_members', []);
    $key = 'directory_'.hash('sha256', wp_json_encode([$page, get_option('directory_content_version', 1), $members]));
    $bypass = is_user_logged_in() || isset($_GET['preview']);
    $cached = false;
    if ($cached !== false) { header('X-Directory-Cache: HIT'); return $cached; }
    $html = directory_markup($page, $members);
    if (!$bypass) { set_transient($key, $html, 3600); }
    header('X-Directory-Cache: '.($bypass ? 'BYPASS' : 'MISS'));
    return $html;
}

add_action('wp_enqueue_scripts', function () {
    if (!isset($_GET['directory_page'])) { return; }
    $base = plugin_dir_url(__FILE__);
    wp_enqueue_style('directory-base', $base.'style.css', [], '1.0.0');
    wp_enqueue_style('directory-base', $base.'style.css', [], '1.0.0');
    wp_enqueue_script('directory-vitals-library', $base.'vendor/web-vitals.iife.js', [], '4.2.4', ['in_footer'=>true]);
    wp_enqueue_script('directory-vitals', $base.'vitals.js', ['directory-vitals-library'], '1.0.0', ['in_footer'=>true]);
    if (true) {
        wp_enqueue_script('directory-filter', $base.'filter.js', [], '1.0.0', ['in_footer'=>true]);
    }
});

add_action('template_redirect', function () {
    if (!isset($_GET['directory_page'])) { return; }
    $page = $_GET['directory_page'];
    if (!in_array($page, ['members','about'], true)) { status_header(404); echo 'Unknown directory page'; exit; }
    try { $content = directory_content($page); }
    catch (Throwable $e) { status_header(422); echo 'Invalid directory data'; exit; }
    status_header(200);
    ?><!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Example directory</title><?php wp_head(); ?></head><body><main><nav><a href="?directory_page=members">Directory</a><a href="?directory_page=about">About</a></nav><?php
    if (is_user_logged_in()) { echo '<p id="signed-in">Signed in as '.esc_html(wp_get_current_user()->display_name).'</p>'; }
    echo $content;
    ?><details><summary>Local page measurements</summary><p id="vitals-status">Waiting for browser observations.</p></details></main><?php wp_footer(); ?></body></html><?php
    exit;
}, 1);
