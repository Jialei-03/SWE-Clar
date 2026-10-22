<?php
function database(array $config): PDO {
    $db=new PDO('sqlite:'.getenv('INSPECTION_DB'));$db->setAttribute(PDO::ATTR_ERRMODE,PDO::ERRMODE_EXCEPTION);
    $db->exec('PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;');
    $db->exec('CREATE TABLE IF NOT EXISTS communities(id TEXT PRIMARY KEY); CREATE TABLE IF NOT EXISTS streets(community TEXT NOT NULL,street TEXT NOT NULL,PRIMARY KEY(community,street),FOREIGN KEY(community) REFERENCES communities(id)); CREATE TABLE IF NOT EXISTS inspections(id TEXT PRIMARY KEY,community TEXT NOT NULL,street TEXT NOT NULL,residence TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ("open","closed")),FOREIGN KEY(community,street) REFERENCES streets(community,street)); CREATE TABLE IF NOT EXISTS initialized(id INTEGER PRIMARY KEY);');
    $db->beginTransaction();
    try {
        if (!$db->query('SELECT 1 FROM initialized')->fetchColumn()) {
            foreach($config['communities'] as $community=>$streets) {
                $db->prepare('INSERT INTO communities VALUES(?)')->execute([$community]);
                foreach($streets as $street)$db->prepare('INSERT INTO streets VALUES(?,?)')->execute([$community,$street]);
            }
            foreach(($config['inspections'] ?? []) as $row)$db->prepare('INSERT INTO inspections VALUES(?,?,?,?,?)')->execute([$row['id'],$row['community'],$row['street'],$row['residence'],$row['status']]);
            $db->exec('INSERT INTO initialized VALUES(1)');
        }
        $db->commit();
    }catch(Throwable $e){$db->rollBack();throw $e;}
    return $db;
}
function command(PDO $db,array $input,string $role): array {
    $kind=$input['type'] ?? '';
    if($kind==='create') {
        if(!in_array($role,['admin','inspector'],true))return ['error'=>['code'=>'forbidden']];
        foreach(['id','community','street','residence'] as $field)if(!isset($input[$field]) || !is_string($input[$field]) || trim($input[$field])==='')return ['error'=>['code'=>'invalid_address']];
        $query=$db->prepare('SELECT 1 FROM streets WHERE community=? AND street=?');$query->execute([$input['community'],$input['street']]);
        if(!$query->fetchColumn())return ['error'=>['code'=>'invalid_address']];
        $q=$db->prepare('SELECT 1 FROM inspections WHERE id=?');$q->execute([$input['id']]);if($q->fetchColumn())return ['error'=>['code'=>'duplicate_id']];
        $db->prepare('INSERT INTO inspections VALUES(?,?,?,?,?)')->execute([$input['id'],$input['community'],$input['street'],$input['residence'],'open']);
        return ['result'=>['id'=>$input['id'],'status'=>'open']];
    }
    if($kind==='delete' || $kind==='report')return ['error'=>['code'=>'not_implemented']];
    return ['error'=>['code'=>'unknown_command']];
}
