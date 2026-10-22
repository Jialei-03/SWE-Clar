<?php
declare(strict_types=1);
require_once __DIR__.'/document.php';
// Feature hooks: keep the working profile administration and PDF preview intact.
function admin(array $actor):void {}
function configureField(SQLite3 $db,array $actor,string $field,array $request):array {fail(501,'not_implemented','Field configuration is unfinished.');}
function uploadAsset(SQLite3 $db,array $actor):array {fail(501,'not_implemented','Image upload is unfinished.');}
function placeAsset(SQLite3 $db,array $actor,string $slot,array $request):array {fail(501,'not_implemented','Image placement is unfinished.');}
function renderDocument(SQLite3 $db,array $actor,array $request):array {
    $kind=$request['kind']??null;$filename=$request['filename']??null;$profile=$request['profile_id']??null;
    if(!in_array($kind,['sample_card','sample_pass'],true)||!is_string($filename)||!preg_match('/^[A-Za-z0-9_-]{1,64}\.pdf$/D',$filename)||!is_string($profile))fail(400,'invalid_request');
    $stored=row($db,'SELECT data FROM profiles WHERE id=:id',['id'=>$profile]);if(!$stored)fail(404,'not_found');
    $values=validatedProfile(json_decode($stored['data'],true));$t=templateState($db);
    $pdf=renderPDF($values,$t,[],$kind);$sha=hash('sha256',$pdf);$bytes=strlen($pdf);
    $s=$db->prepare('INSERT INTO documents VALUES(:filename,:kind,:profile,:data,:bytes,:sha,:revision) ON CONFLICT(filename) DO UPDATE SET kind=excluded.kind,profile_id=excluded.profile_id,data=excluded.data,bytes=excluded.bytes,sha256=excluded.sha256,revision=excluded.revision');
    foreach(['filename'=>$filename,'kind'=>$kind,'profile'=>$profile,'sha'=>$sha] as $key=>$value)$s->bindValue(':'.$key,$value,SQLITE3_TEXT);
    $s->bindValue(':data',$pdf,SQLITE3_BLOB);$s->bindValue(':bytes',$bytes,SQLITE3_INTEGER);$s->bindValue(':revision',$t['revision'],SQLITE3_INTEGER);$s->execute();
    return ['document'=>['filename'=>$filename,'kind'=>$kind,'profile_id'=>$profile,'bytes'=>$bytes,'sha256'=>$sha,'revision'=>$t['revision']]];
}
