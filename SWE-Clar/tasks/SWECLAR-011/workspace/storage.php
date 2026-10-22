<?php
declare(strict_types=1);
const FIELDS=['document_id','name','group','contact','reviewer','reference'];
const SLOTS=['front_left','front_right','back','watermark'];
class ApiError extends RuntimeException {
    public function __construct(public int $status,public string $kind,string $message='') {parent::__construct($message?:str_replace('_',' ',$kind));}
}
function fail(int $status,string $code,string $message=''):never {throw new ApiError($status,$code,$message);}
function directory():string {return getenv('DOCUMENT_DATA_DIR')?:__DIR__.'/data';}
function database():SQLite3 {
    $path=directory();if(!is_dir($path)&&!mkdir($path,0700,true))throw new RuntimeException('Cannot create data directory');
    $db=new SQLite3($path.'/application.sqlite');$db->enableExceptions(true);$db->busyTimeout(10000);return $db;
}
function query(SQLite3 $db,string $sql,array $values=[]):SQLite3Result {
    $s=$db->prepare($sql);
    foreach($values as $name=>$value){$type=is_int($value)?SQLITE3_INTEGER:($value===null?SQLITE3_NULL:SQLITE3_TEXT);$s->bindValue(':'.$name,$value,$type);}
    return $s->execute();
}
function rows(SQLite3 $db,string $sql,array $values=[]):array {$r=query($db,$sql,$values);$out=[];while($v=$r->fetchArray(SQLITE3_ASSOC))$out[]=$v;return $out;}
function row(SQLite3 $db,string $sql,array $values=[]):?array {return rows($db,$sql,$values)[0]??null;}
function encode(mixed $v):string {return json_encode($v,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);}
function defaults():array {return ['color'=>'#000000','background'=>null,'font_size'=>10,'weight'=>'normal','border'=>false,'visible'=>true];}
function initDatabase(bool $reset):void {
    $path=directory().'/application.sqlite';if($reset&&is_file($path))unlink($path);
    $db=database();$db->exec('CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, role TEXT NOT NULL, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, actor_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS template(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, styles TEXT NOT NULL, placements TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, data BLOB NOT NULL, sha256 TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS documents(filename TEXT PRIMARY KEY, kind TEXT NOT NULL, profile_id TEXT NOT NULL, data BLOB NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL, type TEXT NOT NULL, target TEXT NOT NULL, revision INTEGER NOT NULL, timestamp INTEGER NOT NULL);');
    foreach(['admin-a'=>'admin','admin-b'=>'admin','editor-a'=>'editor'] as $id=>$role)query($db,'INSERT OR IGNORE INTO accounts VALUES(:id,:role,:password)',['id'=>$id,'role'=>$role,'password'=>password_hash('demo-pass',PASSWORD_BCRYPT)]);
    $styles=[];foreach(FIELDS as $field)$styles[$field]=defaults();
    query($db,'INSERT OR IGNORE INTO template VALUES(1,0,:styles,:placements)',['styles'=>encode($styles),'placements'=>encode(array_fill_keys(SLOTS,null))]);
    foreach(json_decode(file_get_contents(__DIR__.'/fixtures/demo.json'),true,flags:JSON_THROW_ON_ERROR) as $profile)query($db,'INSERT OR IGNORE INTO profiles VALUES(:id,:data)',['id'=>$profile['id'],'data'=>encode($profile['values'])]);
}
function templateState(SQLite3 $db):array {$t=row($db,'SELECT * FROM template WHERE id=1');return ['revision'=>$t['revision'],'styles'=>json_decode($t['styles'],true),'placements'=>json_decode($t['placements'],true)];}
function saveTemplate(SQLite3 $db,array $t):void {query($db,'UPDATE template SET revision=:revision,styles=:styles,placements=:placements WHERE id=1',['revision'=>$t['revision'],'styles'=>encode($t['styles']),'placements'=>encode($t['placements'])]);}
function transaction(SQLite3 $db,callable $action):mixed {
    $db->exec('BEGIN IMMEDIATE');try{$result=$action();$db->exec('COMMIT');return $result;}catch(Throwable $e){$db->exec('ROLLBACK');throw $e;}
}
function audit(SQLite3 $db,array $actor,string $type,string $target,int $revision):void {
    query($db,'INSERT INTO audit(actor_id,type,target,revision,timestamp) VALUES(:actor_id,:type,:target,:revision,:timestamp)',['actor_id'=>$actor['id'],'type'=>$type,'target'=>$target,'revision'=>$revision,'timestamp'=>time()]);
}
function validatedProfile(mixed $values):array {
    if(!is_array($values)||array_diff(FIELDS,array_keys($values))||array_diff(array_keys($values),FIELDS))fail(400,'invalid_profile');
    foreach($values as $value)if(!is_string($value)||!mb_check_encoding($value,'UTF-8')||strlen($value)>160||preg_match('/[\x00-\x1F\x7F]/',$value)||preg_match('/^\s*$/u',$value))fail(400,'invalid_profile');
    $ranges=json_decode(file_get_contents(__DIR__.'/fixtures/supported_codepoints.json'),true)['ranges'];
    foreach($values as $value)foreach(mb_str_split($value) as $character){
        $cp=mb_ord($character);$supported=false;
        foreach($ranges as [$first,$last])if($cp>=$first&&$cp<=$last){$supported=true;break;}
        if(!$supported)fail(400,'invalid_profile','Use characters supported by the supplied bilingual document fonts.');
    }
    return $values;
}
