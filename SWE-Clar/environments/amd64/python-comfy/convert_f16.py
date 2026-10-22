"""Deterministic bounded-memory precision conversion of public safetensors weights.

This changes only F32 storage to IEEE F16, not architecture or trained parameters.
The source and resulting files are SHA-256 recorded by preparation.
"""
import json,struct,sys,hashlib
from pathlib import Path
source=Path(sys.argv[1]);destination=Path(sys.argv[2]);assert source.resolve()!=destination.resolve()
with source.open('rb') as f:
 old_len=struct.unpack('<Q',f.read(8))[0];header=json.loads(f.read(old_len));offset=0;new={};entries=[]
 for key in sorted(header):
  item=header[key]
  if key=='__metadata__':new[key]=item;continue
  size=item['data_offsets'][1]-item['data_offsets'][0];size=size//2 if item['dtype']=='F32' else size
  new[key]={'dtype':'F16' if item['dtype']=='F32' else item['dtype'],'shape':item['shape'],'data_offsets':[offset,offset+size]};offset+=size;entries.append((key,item))
 encoded=json.dumps(new,separators=(',',':'),ensure_ascii=False).encode();encoded+=b' '*((-len(encoded))%8)
 with destination.open('wb') as out:
  out.write(struct.pack('<Q',len(encoded)));out.write(encoded)
  for key,item in entries:
   start,end=item['data_offsets'];f.seek(8+old_len+start);remaining=end-start
   while remaining:
    data=f.read(min(262144,remaining));assert data;remaining-=len(data)
    if item['dtype']=='F32':
     values=struct.unpack('<'+str(len(data)//4)+'f',data);data=struct.pack('<'+str(len(values))+'e',*values)
    out.write(data)
with source.open('rb') as f:source_sha=hashlib.file_digest(f,'sha256').hexdigest()
with destination.open('rb') as f:derived_sha=hashlib.file_digest(f,'sha256').hexdigest()
print(json.dumps({'source_sha256':source_sha,'derived_sha256':derived_sha,'source_bytes':source.stat().st_size,'derived_bytes':destination.stat().st_size,'conversion':'F32 to IEEE F16; other tensors unchanged; deterministic sorted header'}))
