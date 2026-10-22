"""Independent per-RU browser/model checks against the published UI interfaces."""
import argparse,base64,json,os,struct,subprocess,sys,tempfile,traceback,zlib
from pathlib import Path
TESTS=Path(__file__).resolve().parent;PUBLIC=Path('/public_tests')
sys.path.insert(0,str(PUBLIC))
from ui_support import Application,identity

def verify_image(observed,fixture):
 raw=base64.b64decode(observed['encoded'].split(',',1)[1]);assert raw.startswith(b'\x89PNG\r\n\x1a\n'),'Not a fresh PNG'
 assert observed['size']==fixture['size'] and observed['rgba']==fixture['rgba'],'Decoded image pixels differ'
 offset=8;metadata=[];ended=False
 while offset<len(raw):
  length=struct.unpack('>I',raw[offset:offset+4])[0];kind=raw[offset+4:offset+8];data=raw[offset+8:offset+8+length]
  assert len(data)==length and offset+12+length<=len(raw),'Truncated PNG'
  assert zlib.crc32(kind+data)&0xffffffff==struct.unpack('>I',raw[offset+8+length:offset+12+length])[0],'Invalid PNG checksum'
  if kind==b'zTXt':metadata.append(zlib.decompress(data.split(b'\0',1)[1][1:]))
  elif kind==b'iTXt':
   _,rest=data.split(b'\0',1);compressed=rest[0];text=rest[2:].split(b'\0',2)[2];metadata.append(zlib.decompress(text) if compressed else text)
  elif kind in (b'tEXt',b'eXIf'):metadata.append(data)
  offset+=12+length
  if kind==b'IEND':ended=True;break
 assert ended and offset==len(raw),'Incomplete PNG or trailing original data'
 text=b' '.join(metadata)
 assert b'synthetic-metadata-must-not-propagate' not in text and b'Synthetic fixture artist' not in text,'Original metadata propagated'

def model(app):
 script="""const assert=require('assert');const {transition}=require(process.argv[1]);const state={route:'home',openNow:false,error:'',nested:{keep:1}},event={type:'navigate',route:'saved'},config={routes:['home','saved','profile'],protectedRoutes:['profile'],authenticated:true};const before=JSON.stringify([state,event,config]);const result=transition(state,event,config);assert.equal(JSON.stringify([state,event,config]),before);assert.notStrictEqual(result,state);assert.equal(result.route,'saved');assert.deepStrictEqual(result.nested,state.nested);const bad=transition(state,{type:'navigate',route:'missing'},config);assert.equal(bad.route,'home');assert.equal(bad.error,'unknown_route');const denied=transition(state,{type:'navigate',route:'profile'},{...config,authenticated:false});assert.equal(denied.route,'home');assert.equal(denied.error,'auth_required');"""
 r=subprocess.run(['node','-e',script,str(app.dist/'model.cjs')],env=app.environment(),capture_output=True,text=True,timeout=10,**identity())
 assert r.returncode==0,r.stderr[-1600:]

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--gates',default='1,2,3,4,5');args=parser.parse_args();gates=[int(x) for x in args.gates.split(',')];assert gates and all(1<=x<=5 for x in gates)
 results=[];infrastructure=[]
 with tempfile.TemporaryDirectory(prefix='ui-oracle-') as directory:
  root=Path(directory);fixtures=json.loads((TESTS/'image_fixtures.json').read_text())
  for name,fixture in fixtures.items():(root/name).write_bytes(base64.b64decode(fixture['encoded']))
  first=base64.b64decode(fixtures['first.png']['encoded']);(root/'first.png-oversize').write_bytes(first+b'\0'*(5*1024*1024+1-len(first)))
  def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
  wide=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',4097,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+b'\x20\x30\x40'*4097))+chunk(b'IEND',b'')
  (root/'first.png-wide').write_bytes(wide)
  edge=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',4096,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+b'\x20\x30\x40'*4096))+chunk(b'IEND',b'')
  (root/'first.png-edge').write_bytes(edge)
  # Valid ancillary chunk before IEND, bringing encoded file size to exactly 5 MiB.
  padded=first[:-12]+chunk(b'npAD',b'\0'*(5*1024*1024-len(first)-12))+first[-12:]
  assert len(padded)==5*1024*1024
  (root/'first.png-size-edge').write_bytes(padded)

  for gate in gates:
   try:
    with Application() as app:
     if gate==1:model(app)
     env={**os.environ,'UI_BROWSER_HOME':str(app.project/'runtime'),'UI_BROWSER_WRAPPER':str(PUBLIC/'browser_launch.py')}
     r=subprocess.run(['node',str(TESTS/'ui_probe.cjs'),app.url,str(root/'first.png'),str(root/'second.png'),str(root/'sample.jpg'),str(gate)],env=env,capture_output=True,text=True,timeout=30)
     assert r.returncode==0,r.stderr[-1800:]
     observed=json.loads(r.stdout);assert observed['rendered'] and not observed['errors'] and not observed['remote'],observed
     if gate==2:assert observed['saved'] and observed['unknown'] and observed['guard'],observed
     if gate==3:assert observed['label'] and observed['box'],observed
     if gate==4:
      assert observed['rating']=='4.3' and observed['moved']!=0 and observed['radiusAfter']!=observed['radiusBefore'],observed
      assert observed['locked'] and observed['restored'] and observed['cancelled'],observed
      assert observed['ratingCases']==['4.0','0.0','2.3'],observed
     if gate==5:
      assert all(observed[k] for k in ['changed','accountSame','corrupt','unsupported','cancelPreserves']),{k:v for k,v in observed.items() if 'Image' not in k and k!='image'}
      assert observed['resourceAccepted']==[True,True],observed['resourceAccepted']
      assert observed['resourceRejected']==[True,True],observed['resourceRejected']
      try:
       verify_image(observed['image'],fixtures['first.png']);verify_image(observed['latestImage'],fixtures['second.png']);verify_image(observed['jpegImage'],fixtures['sample.jpg'])
      except (KeyError,TypeError,ValueError,IndexError,struct.error,zlib.error) as e:
       raise AssertionError('Candidate image encoding is invalid: '+str(e)) from e
    results.append({'ru_id':f'RU-{gate:03d}','passed':True})
   except AssertionError as e:results.append({'ru_id':f'RU-{gate:03d}','passed':False,'detail':str(e) or type(e).__name__,'trace':traceback.format_exc()[-1800:]})
   except Exception as e:infrastructure.append({'gate':gate,'type':type(e).__name__,'detail':str(e),'trace':traceback.format_exc()[-1800:]})
 return {'harness_ok':not infrastructure,'results':results,'infrastructure_errors':infrastructure}
if __name__=='__main__':print(json.dumps(main()))
