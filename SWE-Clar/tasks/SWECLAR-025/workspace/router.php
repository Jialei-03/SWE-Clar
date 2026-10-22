<?php
$path=parse_url($_SERVER['REQUEST_URI'],PHP_URL_PATH);
if(!str_starts_with($path,'/api/'))return false;
header('Content-Type: application/json');
function reply(int $status,array $value): never {http_response_code($status);echo json_encode($value);exit;}
try {
    $config=json_decode(file_get_contents(getenv('INSPECTION_CONFIG')),true,512,JSON_THROW_ON_ERROR);
    $authorization=$_SERVER['HTTP_AUTHORIZATION'] ?? '';
    $role=str_starts_with($authorization,'Bearer ')?($config['access_codes'][substr($authorization,7)] ?? null):null;
    if(!in_array($role,['admin','inspector','office'],true))reply(401,['error'=>['code'=>'unauthenticated']]);
    require __DIR__.'/InspectionService.php';$db=database($config);
    if($path==='/api/context' && $_SERVER['REQUEST_METHOD']==='GET') {
        $groups=[];foreach($db->query('SELECT community,street FROM streets ORDER BY community,street')->fetchAll(PDO::FETCH_ASSOC) as $row)$groups[$row['community']][]=$row['street'];
        reply(200,['role'=>$role,'communities'=>$groups,'inspections'=>$db->query('SELECT * FROM inspections ORDER BY id')->fetchAll(PDO::FETCH_ASSOC)]);
    }
    if($path!=='/api/command' || $_SERVER['REQUEST_METHOD']!=='POST')reply(404,['error'=>['code'=>'not_found']]);
    $input=json_decode(file_get_contents('php://input'),true,512,JSON_THROW_ON_ERROR);if(!is_array($input))reply(400,['error'=>['code'=>'invalid_request']]);
    $db->exec('BEGIN IMMEDIATE');
    try{$result=command($db,$input,$role);$db->exec(isset($result['error'])?'ROLLBACK':'COMMIT');}
    catch(Throwable $e){$db->exec('ROLLBACK');throw $e;}
    reply(isset($result['error'])?400:200,$result);
}catch(Throwable $e){reply(400,['error'=>['code'=>'invalid_request']]);}
