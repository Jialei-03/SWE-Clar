import base64,hashlib,json
from copy import deepcopy
from candidate_proxy import run

PAYLOAD=bytes(range(256))*4097
ASSET={'id':'asset-a','folder':'media','filename':'sample.bin','title':'Synthetic asset','metadata':{'rights':{'allowed':True,'regions':['north','south']},'tags':['blue','green'],'n':3}}
RULE={'media':{'aem_path':'/content/dam/demo','taxonomy':'demo/media','dynamic_media':True}}
TARGET='destination/content/dam/demo/sample.bin';SIDECAR=TARGET+'.metadata.json'
def encoded(data):return {'base64':base64.b64encode(data).decode()}
def fixture():return {'files':{'source/media/sample.bin':{'base64':base64.b64encode(bytes(range(256))).decode(),'repeat':4097},'source/media/small.txt':encoded(b'example\x00bytes\xff')}}
def operation(assets=None,taxonomy=None,**kw):return {'assets':[deepcopy(ASSET)] if assets is None else assets,'taxonomy':deepcopy(RULE) if taxonomy is None else taxonomy,**kw}
def report(row):return row['value']['report']
def expected():return {**{k:ASSET[k] for k in ['id','filename','title','metadata']},'aem_path':'/content/dam/demo','taxonomy':'demo/media','dynamic_media':True,'sha256':hashlib.sha256(PAYLOAD).hexdigest()}
def fields(row,want):assert all(k in row and row[k]==v for k,v in want.items()),row
def sidecar(row,path=SIDECAR):return json.loads(base64.b64decode(row['files'][path]['base64']))
def success(row):assert not report(row)['errors'] and len(report(row)['migrated'])==1

def test_ru_001_real_copy():
 r=run({**fixture(),'operations':[operation(),operation(via='cli',destination='destination/cli')]});row=r['observations'][0];success(row);assert row['files'][TARGET]['size']==len(PAYLOAD) and row['files'][TARGET]['sha256']==hashlib.sha256(PAYLOAD).hexdigest();fields(report(row)['migrated'][0],{'aem_path':'/content/dam/demo','taxonomy':'demo/media'});assert r['observations'][1]['files']['destination/cli/content/dam/demo/sample.bin']['sha256']==hashlib.sha256(PAYLOAD).hexdigest()

def test_ru_002_metadata_digest():
 row=run({**fixture(),'operations':[operation()]})['observations'][0];success(row);fields(sidecar(row),expected());fields(report(row)['migrated'][0],expected());assert row['files'][TARGET]['sha256']==expected()['sha256']
 # Omit each default independently, then both, through function and CLI paths.
 for omitted in [('title',),('metadata',),('title','metadata')]:
  minimal={k:v for k,v in ASSET.items() if k not in omitted};want={**expected(),**{k:'' if k=='title' else {} for k in omitted}}
  for via in ['function','cli']:
   row=run({**fixture(),'operations':[operation([minimal],via=via)]})['observations'][0];success(row);fields(sidecar(row),want);fields(report(row)['migrated'][0],want);assert row['files'][TARGET]['sha256']==want['sha256']


def test_ru_003_validation_replay_atomicity():
 bad=[{'id':'empty','folder':'media'},{'id':'missing-folder','filename':'x'},{'id':'unmapped','folder':'unknown','filename':'x'},{'id':'absent','folder':'media','filename':'absent'},{'id':'escape','folder':'media','filename':'../sample.bin'}]
 r=run({**fixture(),'operations':[operation(bad+[ASSET]),operation(),operation([{**ASSET,'id':'changed'}])]});a,b,c=r['observations'];assert [e['code'] for e in report(a)['errors']]==['missing_fields','missing_fields','unmapped_folder','missing_asset','invalid_path'];assert [x['id'] for x in report(a)['migrated']]==['asset-a'];success(b);assert b['files']==a['files'];assert report(c)['errors'][0]['code']=='target_conflict' and c['files']==b['files']
 # Equivalent existing sidecar formatting and extra fields are not conflicts.
 files=fixture()['files'];files[TARGET]=encoded(PAYLOAD);files[SIDECAR]=encoded(json.dumps({**expected(),'note':'permitted'},indent=4).encode());r=run({'files':files,'operations':[operation()]});success(r['observations'][0]);assert r['before']==r['observations'][0]['files']
 # Traversal and symlink escape must not write outside the repository.
 mapping={**RULE,'alias':{'aem_path':'/content/dam/demo','taxonomy':'alias'}}
 request={**fixture(),'symlinks':[{'path':'destination/content/dam/link','target':'outside','directory':True},{'path':'source/alias','target':'outside','directory':True}],'operations':[operation(taxonomy={'media':{'aem_path':'/content/dam/../../outside','taxonomy':'x'}}),operation(taxonomy={'media':{'aem_path':'/content/dam/link','taxonomy':'x'}}),operation([{**ASSET,'folder':'alias'}],mapping),operation(destination='source/nested')]}
 out=run(request)
 for row in out['observations']:assert report(row)['errors'][0]['code']=='invalid_path' and row['files']==out['before']
 # Incomplete output pairs are preserved as conflicts.
 files=fixture()['files'];files[TARGET]=encoded(b'occupied');out=run({'files':files,'operations':[operation()]});assert report(out['observations'][0])['errors'][0]['code']=='target_conflict';assert out['before']==out['observations'][0]['files']
 # OS file-size limit triggers a real sidecar write failure; later small record still succeeds.
 bad={**ASSET,'filename':'small.txt','metadata':{'large':'x'*4096}};good={**ASSET,'id':'later','filename':'good.txt','metadata':{}};files=fixture()['files'];files['source/media/good.txt']=encoded(b'ok');out=run({'files':files,'file_limit':1024,'operations':[operation([bad,good])]});row=out['observations'][0];assert len(report(row)['errors'])==1 and report(row)['errors'][0]['index']==0 and report(row)['errors'][0]['code'];assert [x['id'] for x in report(row)['migrated']]==['later'];dest={p for p in row['files'] if p.startswith('destination/')};assert dest=={'destination/content/dam/demo/good.txt','destination/content/dam/demo/good.txt.metadata.json'}


def test_ru_004_dynamic_metadata():
 mapping={'media':{k:v for k,v in RULE['media'].items() if k!='dynamic_media'}}
 out=run({**fixture(),'operations':[operation(),operation(taxonomy=mapping,destination='destination/default'),operation(taxonomy={'media':{**RULE['media'],'dynamic_media':'yes'}},destination='destination/bad')]})
 for row,path,flag in [(out['observations'][0],SIDECAR,True),(out['observations'][1],'destination/default/content/dam/demo/sample.bin.metadata.json',False)]:success(row);assert report(row)['migrated'][0]['dynamic_media'] is flag and sidecar(row,path)['dynamic_media'] is flag
 assert report(out['observations'][2])['errors'] and not any(p.startswith('destination/bad/') for p in out['observations'][2]['files'])


def test_ru_005_order_summary_inputs():
 assets=[{**ASSET,'id':'second','filename':'small.txt'}, {'id':'bad','folder':'unknown','filename':'x'},ASSET]
 row=run({**fixture(),'operations':[operation(assets)]})['observations'][0];r=report(row);assert [x['id'] for x in r['migrated']]==['second','asset-a'];assert r['errors'][0]['index']==1;fields(r['summary'],{'input':3,'migrated':2,'failed':1})
