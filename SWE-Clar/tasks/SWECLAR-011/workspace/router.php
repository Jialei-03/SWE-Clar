<?php
declare(strict_types=1);
ini_set('display_errors','0');
require __DIR__.'/storage.php';require __DIR__.'/features.php';
function jsonResponse(mixed $data,int $status=200):never {http_response_code($status);header('Content-Type: application/json; charset=utf-8');header('Cache-Control: no-store');echo encode($data);exit;}
function body():array {
    try{$raw=json_decode(file_get_contents('php://input'),false,flags:JSON_THROW_ON_ERROR);if(!is_object($raw))fail(400,'invalid_json');return json_decode(json_encode($raw),true,flags:JSON_THROW_ON_ERROR);}catch(JsonException){fail(400,'invalid_json');}
}
function actor(SQLite3 $db):array {
    $token=$_COOKIE['document_session']??'';
    $user=row($db,'SELECT a.id,a.role FROM sessions s JOIN accounts a ON a.id=s.actor_id WHERE s.token=:token',['token'=>$token]);if(!$user)fail(401,'authentication_required');return $user;
}
try{
    $method=$_SERVER['REQUEST_METHOD'];$path=parse_url($_SERVER['REQUEST_URI'],PHP_URL_PATH);
    $static=['/'=>['web/index.html','text/html; charset=utf-8'],'/ui.js'=>['web/ui.js','text/javascript'],'/style.css'=>['web/style.css','text/css']];
    if(isset($static[$path])&&$method==='GET'){header('Content-Type: '.$static[$path][1]);readfile(__DIR__.'/'.$static[$path][0]);exit;}
    if(!str_starts_with($path,'/api/'))fail(404,'not_found');
    $db=database();
    if($path==='/api/login'&&$method==='POST'){
        $r=body();$username=$r['username']??null;$password=$r['password']??null;
        $user=is_string($username)?row($db,'SELECT * FROM accounts WHERE id=:id',['id'=>$username]):null;
        if(!$user||!is_string($password)||!password_verify($password,$user['password']))fail(401,'invalid_credentials');
        $token=bin2hex(random_bytes(32));query($db,'INSERT INTO sessions VALUES(:token,:actor)',['token'=>$token,'actor'=>$user['id']]);
        setcookie('document_session',$token,['path'=>'/','httponly'=>true,'samesite'=>'Strict']);jsonResponse(['user'=>['id'=>$user['id'],'role'=>$user['role']]]);
    }
    $who=actor($db);
    if($path==='/api/session'&&$method==='GET')jsonResponse(['user'=>$who]);
    if($path==='/api/logout'&&$method==='POST'){
        query($db,'DELETE FROM sessions WHERE token=:token',['token'=>$_COOKIE['document_session']]);setcookie('document_session','',['expires'=>1,'path'=>'/','httponly'=>true,'samesite'=>'Strict']);jsonResponse(['ok'=>true]);
    }
    if($path==='/api/profiles'&&$method==='GET')jsonResponse(['profiles'=>array_map(fn($r)=>['id'=>$r['id'],'values'=>json_decode($r['data'],true)],rows($db,'SELECT * FROM profiles ORDER BY id'))]);
    if($path==='/api/profiles'&&$method==='POST'){
        $r=body();$id=$r['id']??null;$values=validatedProfile($r['values']??null);
        if(!is_string($id)||!preg_match('/^[a-z][a-z0-9-]{0,39}$/D',$id))fail(400,'invalid_profile');
        transaction($db,function()use($db,$id,$values){if(row($db,'SELECT id FROM profiles WHERE id=:id',['id'=>$id]))fail(409,'profile_exists');query($db,'INSERT INTO profiles VALUES(:id,:data)',['id'=>$id,'data'=>encode($values)]);});
        jsonResponse(['profile'=>['id'=>$id,'values'=>$values]],201);
    }
    if(preg_match('~^/api/profiles/([a-z][a-z0-9-]{0,39})$~D',$path,$m)&&$method==='PUT'){
        $r=body();$values=validatedProfile($r['values']??null);$id=$m[1];
        transaction($db,function()use($db,$id,$values){if(!row($db,'SELECT id FROM profiles WHERE id=:id',['id'=>$id]))fail(404,'not_found');query($db,'UPDATE profiles SET data=:data WHERE id=:id',['id'=>$id,'data'=>encode($values)]);});jsonResponse(['profile'=>['id'=>$id,'values'=>$values]]);
    }
    if($path==='/api/template'&&$method==='GET')jsonResponse(templateState($db));
    if(preg_match('~^/api/template/fields/([^/]+)$~D',$path,$m)&&$method==='PATCH'){admin($who);jsonResponse(configureField($db,$who,$m[1],body()));}
    if(preg_match('~^/api/template/placements/([^/]+)$~D',$path,$m)&&$method==='PUT'){admin($who);jsonResponse(placeAsset($db,$who,$m[1],body()));}
    if($path==='/api/assets'&&$method==='POST')jsonResponse(uploadAsset($db,$who),201);
    if($path==='/api/assets'&&$method==='GET')jsonResponse(['assets'=>rows($db,'SELECT id,sha256,width,height FROM assets ORDER BY id')]);
    if(preg_match('~^/api/assets/([a-f0-9]{32})$~D',$path,$m)&&$method==='GET'){
        $a=row($db,'SELECT data FROM assets WHERE id=:id',['id'=>$m[1]]);if(!$a)fail(404,'not_found');header('Content-Type: image/png');header('Cache-Control: no-store');echo $a['data'];exit;
    }
    if($path==='/api/render'&&$method==='POST')jsonResponse(renderDocument($db,$who,body()),201);
    if($path==='/api/documents'&&$method==='GET')jsonResponse(['documents'=>rows($db,'SELECT filename,kind,profile_id,bytes,sha256,revision FROM documents ORDER BY filename')]);
    if(preg_match('~^/api/documents/([A-Za-z0-9_-]{1,64}\.pdf)$~D',$path,$m)&&$method==='GET'){
        $d=row($db,'SELECT data FROM documents WHERE filename=:filename',['filename'=>$m[1]]);if(!$d)fail(404,'not_found');header('Content-Type: application/pdf');header('Content-Disposition: attachment; filename="'.$m[1].'"');header('Content-Length: '.strlen($d['data']));header('Cache-Control: no-store');echo $d['data'];exit;
    }
    if($path==='/api/audit'&&$method==='GET')jsonResponse(['events'=>rows($db,'SELECT * FROM audit ORDER BY id')]);
    fail(404,'not_found');
}catch(ApiError $e){jsonResponse(['error'=>['code'=>$e->kind,'message'=>$e->getMessage()]],$e->status);}catch(Throwable $e){error_log($e->getMessage());jsonResponse(['error'=>['code'=>'internal_error','message'=>'The operation could not be completed.']],500);}
