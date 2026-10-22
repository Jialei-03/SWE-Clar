const fs=require('node:fs/promises');
const crypto=require('node:crypto');
const path=require('node:path');

const own=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
const dictionary=()=>({});
const clone=value=>structuredClone(value);

function put(object,key,value){
  // Object.defineProperty also makes S3 keys such as "__proto__" ordinary keys.
  Object.defineProperty(object,key,{value,writable:true,enumerable:true,configurable:true});
}

function emptyState(){
  return {images:dictionary(),faces:dictionary(),groups:dictionary(),nextGroup:1};
}

function validFaceId(value){
  return typeof value==='string'&&value.length>0&&value.length<=1024&&value.trim()===value;
}

function uniqueStrings(values,validator=()=>true){
  const result=[];
  const seen=new Set();
  if(!Array.isArray(values))return result;
  for(const value of values){
    if(typeof value==='string'&&validator(value)&&!seen.has(value)){
      seen.add(value);result.push(value);
    }
  }
  return result;
}

function sourceArray(value,fields){
  if(!value||typeof value!=='object')return [];
  for(const field of fields){
    if(Array.isArray(value[field]))return value[field];
    // A few older local state files represented an association set as an
    // object.  Reading its keys is safe and still discards all provider
    // metadata.
    if(value[field]&&typeof value[field]==='object'&&!Array.isArray(value[field]))return Object.keys(value[field]);
  }
  return [];
}

function imageMime(bytes){
  if(bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))return 'image/png';
  if(bytes.length>=2&&bytes[0]===255&&bytes[1]===216)return 'image/jpeg';
  return null;
}

function stateFrom(value){
  if(!value||typeof value!=='object'||Array.isArray(value))throw Error('Invalid catalogue state');
  const result=emptyState();

  if(value.images!==undefined){
    if(!value.images||typeof value.images!=='object'||Array.isArray(value.images))throw Error('Invalid image state');
    for(const key of Object.keys(value.images)){
      const item=value.images[key];
      if(!item||typeof item!=='object'||typeof item.bytes!=='string')throw Error('Invalid image state');
      let mime=item.mime;
      if(mime!=='image/png'&&mime!=='image/jpeg'){
        try{mime=imageMime(Buffer.from(item.bytes,'base64'));}catch{mime=null;}
      }
      if(mime!=='image/png'&&mime!=='image/jpeg')throw Error('Invalid image media type');
      const faceIds=uniqueStrings(sourceArray(item,['face_ids','faceIds','faces']),validFaceId);
      put(result.images,key,{bytes:item.bytes,mime,face_ids:faceIds});
    }
  }

  if(value.groups!==undefined){
    if(!value.groups||typeof value.groups!=='object'||Array.isArray(value.groups))throw Error('Invalid group state');
    for(const id of Object.keys(value.groups)){
      const item=value.groups[id];
      if(!item||typeof item!=='object')throw Error('Invalid group state');
      const name=typeof item.name==='string'&&item.name.trim()?item.name.trim():null;
      const faceIds=uniqueStrings(sourceArray(item,['face_ids','faceIds','faces']),validFaceId);
      const imageKeys=uniqueStrings(sourceArray(item,['image_keys','imageKeys','images']),value=>typeof value==='string');
      put(result.groups,id,{name,face_ids:faceIds,image_keys:imageKeys});
    }
  }

  if(value.faces!==undefined){
    if(!value.faces||typeof value.faces!=='object'||Array.isArray(value.faces))throw Error('Invalid face state');
    for(const faceId of Object.keys(value.faces)){
      const groupId=value.faces[faceId];
      if(validFaceId(faceId)&&typeof groupId==='string'&&own(result.groups,groupId))put(result.faces,faceId,groupId);
    }
  }

  // Keep the two association directions usable even when loading a state
  // written by an earlier version of the local component.
  for(const groupId of Object.keys(result.groups)){
    const group=result.groups[groupId];
    for(const faceId of group.face_ids){
      if(!own(result.faces,faceId))put(result.faces,faceId,groupId);
    }
  }
  for(const key of Object.keys(result.images)){
    const image=result.images[key];
    for(const faceId of image.face_ids){
      const groupId=result.faces[faceId];
      if(typeof groupId==='string'&&own(result.groups,groupId)){
        const group=result.groups[groupId];
        if(!group.face_ids.includes(faceId))group.face_ids.push(faceId);
        if(!group.image_keys.includes(key))group.image_keys.push(key);
      }
    }
  }

  let next=Number.isInteger(value.nextGroup)&&value.nextGroup>0?value.nextGroup:1;
  for(const id of Object.keys(result.groups)){
    const match=/^group-(\d+)$/.exec(id);
    if(match)next=Math.max(next,Number(match[1])+1);
  }
  result.nextGroup=next;
  return result;
}

function imageValue(value){
  let bytes=value;
  let suppliedMime;
  if(value&&typeof value==='object'&&!Buffer.isBuffer(value)&&!(value instanceof Uint8Array)&&!(value instanceof ArrayBuffer)){
    if(own(value,'bytes')){bytes=value.bytes;suppliedMime=value.mime;}
    else if(own(value,'Bytes')){bytes=value.Bytes;suppliedMime=value.mime||value.Mime;}
  }
  if(bytes instanceof ArrayBuffer)bytes=new Uint8Array(bytes);
  if(!Buffer.isBuffer(bytes)&&!(bytes instanceof Uint8Array))throw Error('Invalid image bytes');
  bytes=Buffer.from(bytes);
  if(!bytes.length||bytes.length>5000000)throw Error('Invalid image size');
  const mime=imageMime(bytes);
  if(!mime)throw Error('Unsupported image');
  if(suppliedMime!==undefined&&suppliedMime!==mime&&!(suppliedMime==='image/jpg'&&mime==='image/jpeg'))throw Error('Invalid image media type');
  return {bytes,mime};
}

function indexedFaceIds(response){
  const records=Array.isArray(response)?response:response&&response.FaceRecords;
  if(!Array.isArray(records)||records.length===0)throw Error('No indexed faces');
  const ids=[];
  const seen=new Set();
  for(const record of records){
    const id=record&&record.Face&&record.Face.FaceId;
    if(!validFaceId(id)||seen.has(id))throw Error('Invalid indexed face IDs');
    seen.add(id);ids.push(id);
  }
  return ids;
}

function searchMatches(response){
  const matches=Array.isArray(response)?response:response&&response.FaceMatches;
  if(!Array.isArray(matches))throw Error('Invalid face search response');
  const result=[];
  for(const match of matches){
    const id=match&&match.Face&&match.Face.FaceId;
    if(!validFaceId(id))throw Error('Invalid face search match');
    // Rekognition returns a numeric similarity.  Non-finite numeric values
    // are valid policy input but are deliberately not eligible to form a
    // group; a non-numeric field is a malformed provider response.
    if(typeof match.Similarity!=='number')throw Error('Invalid face similarity');
    if(Number.isFinite(match.Similarity)&&match.Similarity>90)result.push(id);
  }
  return result;
}

class Catalog {
  constructor(file,provider){
    this.file=file;
    this.provider=provider;
    this.state=emptyState();
    // Catalog is also safe for callers which invoke mutations directly.  The
    // HTTP server has a queue as well, but this inner queue prevents a pair of
    // simultaneous direct ingests from both indexing the same key.
    this.tail=Promise.resolve();
  }

  enqueue(operation){
    const run=this.tail.then(operation);
    this.tail=run.catch(()=>{});
    return run;
  }

  async load(){
    await this.tail;
    try{
      this.state=stateFrom(JSON.parse(await fs.readFile(this.file,'utf8')));
    }catch(error){
      if(error&&error.code==='ENOENT')return;
      throw error;
    }
  }

  async commit(next){
    const stored=stateFrom(next);
    await fs.mkdir(path.dirname(this.file),{recursive:true});
    const temporary=this.file+'.pending';
    try{
      await fs.writeFile(temporary,JSON.stringify(stored),'utf8');
      await fs.rename(temporary,this.file);
      this.state=stored;
    }finally{
      await fs.rm(temporary,{force:true});
    }
  }

  async ingest(key){
    return this.enqueue(()=>this.indexOne(key));
  }

  async indexOne(key){
    if(typeof key!=='string'||key.length===0)throw Error('Invalid image key');
    if(own(this.state.images,key))return {duplicate:true};

    // Nothing below changes local state until all provider calls have
    // succeeded and the complete next state has been assembled.
    const fetched=await this.provider.image(key);
    const {bytes,mime}=imageValue(fetched);
    const externalId=crypto.createHash('sha256').update(bytes).digest('hex');
    // Give the adapter its own copy so a provider implementation cannot
    // accidentally alter the bytes that are committed as the preview.
    const indexed=await this.provider.index(Buffer.from(bytes),externalId);
    const faceIds=indexedFaceIds(indexed);
    const searches=[];
    for(const faceId of faceIds){
      const response=await this.provider.matches(faceId);
      searches.push(searchMatches(response));
    }

    const next=stateFrom(clone(this.state));
    this.applyIndex(next,key,bytes,mime,faceIds,searches);
    await this.commit(next);
    return {duplicate:false};
  }

  groupOrder(state){
    const ids=Object.keys(state.groups);
    const positions=new Map(ids.map((id,index)=>[id,index]));
    const number=id=>{
      const match=/^group-(\d+)$/.exec(id);
      return match?Number(match[1]):null;
    };
    ids.sort((left,right)=>{
      const a=number(left),b=number(right);
      if(a!==null&&b!==null&&a!==b)return a-b;
      if(a!==null&&b===null)return -1;
      if(a===null&&b!==null)return 1;
      return positions.get(left)-positions.get(right);
    });
    return ids;
  }

  earliestGroup(state,ids){
    const order=this.groupOrder(state);
    const rank=new Map(order.map((id,index)=>[id,index]));
    return [...ids].sort((a,b)=>(rank.get(a)??Number.MAX_SAFE_INTEGER)-(rank.get(b)??Number.MAX_SAFE_INTEGER))[0];
  }

  newGroup(state){
    let id;
    do{id=`group-${state.nextGroup++}`;}while(own(state.groups,id));
    put(state.groups,id,{name:null,face_ids:[],image_keys:[]});
    return id;
  }

  appendUnique(array,value){if(!array.includes(value))array.push(value);}

  applyIndex(state,key,bytes,mime,faceIds,searches){
    const candidateGroups=new Map();
    for(let index=0;index<faceIds.length;index++){
      const candidates=new Set();
      const addFaceGroup=faceId=>{
        if(own(state.faces,faceId)&&typeof state.faces[faceId]==='string'&&own(state.groups,state.faces[faceId]))candidates.add(state.faces[faceId]);
      };
      // A provider is allowed to return an already-known FaceId.  It then
      // belongs to that known group rather than creating a second local one.
      addFaceGroup(faceIds[index]);
      for(const matchId of searches[index]||[])addFaceGroup(matchId);
      candidateGroups.set(faceIds[index],candidates);
    }

    // Union groups named by the same indexed face.  This gives the required
    // transitive merge when one new face connects more than two known groups.
    const parent=new Map();
    const find=value=>{
      let root=value;
      while(parent.get(root)!==root)root=parent.get(root);
      while(parent.get(value)!==value){const next=parent.get(value);parent.set(value,root);value=next;}
      return root;
    };
    const union=(left,right)=>{
      const a=find(left),b=find(right);
      if(a!==b)parent.set(b,a);
    };
    for(const candidates of candidateGroups.values()){
      for(const groupId of candidates)if(!parent.has(groupId))parent.set(groupId,groupId);
      const first=candidates.values().next().value;
      if(first!==undefined)for(const groupId of candidates)union(first,groupId);
    }

    const components=new Map();
    for(const groupId of parent.keys()){
      const root=find(groupId);
      if(!components.has(root))components.set(root,new Set());
      components.get(root).add(groupId);
    }
    const canonicalByGroup=new Map();
    for(const groups of components.values()){
      let assigned;
      for(const groupId of groups){
        const name=state.groups[groupId]&&state.groups[groupId].name;
        if(typeof name==='string'&&name){
          if(assigned!==undefined&&assigned!==name)throw Error('Conflicting group names');
          assigned=name;
        }
      }
      const canonical=this.earliestGroup(state,groups);
      for(const groupId of groups)canonicalByGroup.set(groupId,canonical);
    }

    // Merge each component before attaching the new image.  Only the small
    // catalogue fields are copied; provider FaceDetail data is never carried
    // into local state.
    for(const groups of components.values()){
      const canonical=this.earliestGroup(state,groups);
      const merged={name:null,face_ids:[],image_keys:[]};
      for(const groupId of groups){
        const group=state.groups[groupId];
        if(typeof group.name==='string'&&group.name&&!merged.name)merged.name=group.name;
        for(const faceId of group.face_ids)this.appendUnique(merged.face_ids,faceId);
        for(const imageKey of group.image_keys)this.appendUnique(merged.image_keys,imageKey);
      }
      for(const groupId of groups)if(groupId!==canonical)delete state.groups[groupId];
      put(state.groups,canonical,merged);
    }

    // Keep the reverse face index and group face arrays in agreement, including
    // state produced by an older version which may have omitted one side.
    for(const faceId of Object.keys(state.faces)){
      const groupId=state.faces[faceId];
      if(canonicalByGroup.has(groupId))put(state.faces,faceId,canonicalByGroup.get(groupId));
    }
    for(const groupId of Object.keys(state.groups)){
      const group=state.groups[groupId];
      for(const faceId of Object.keys(state.faces))if(state.faces[faceId]===groupId)this.appendUnique(group.face_ids,faceId);
    }

    const targets=new Map();
    for(const faceId of faceIds){
      const candidates=candidateGroups.get(faceId);
      let target;
      if(candidates&&candidates.size){
        const first=candidates.values().next().value;
        target=canonicalByGroup.get(first)||first;
      }else if(own(state.faces,faceId)&&own(state.groups,state.faces[faceId])){
        target=state.faces[faceId];
      }else{
        target=this.newGroup(state);
      }
      targets.set(faceId,target);
    }

    for(const [faceId,groupId] of targets){
      const group=state.groups[groupId];
      this.appendUnique(group.face_ids,faceId);
      this.appendUnique(group.image_keys,key);
      put(state.faces,faceId,groupId);
    }
    put(state.images,key,{bytes:bytes.toString('base64'),mime,face_ids:[...faceIds]});
  }

  async scan(){
    return this.enqueue(()=>this.scanNow());
  }

  async scanNow(){
    const keys=await this.provider.keys();
    if(!Array.isArray(keys))throw Error('Invalid object listing');
    const seen=new Set();
    const results=[];
    for(const key of keys){
      if(typeof key!=='string')throw Error('Invalid object listing');
      if(seen.has(key))continue;
      seen.add(key);
      results.push({key,...await this.indexOne(key)});
    }
    return {images:results};
  }

  async label(id,name){
    return this.enqueue(()=>this.labelNow(id,name));
  }

  async labelNow(id,name){
    if(typeof id!=='string'||!own(this.state.groups,id))throw Error('Unknown group');
    if(typeof name!=='string'||!name.trim())throw Error('Invalid group name');
    const next=stateFrom(clone(this.state));
    next.groups[id].name=name.trim();
    await this.commit(next);
    return {group_id:id,name:name.trim()};
  }

  list(query=''){
    const text=typeof query==='string'?query:String(query??'');
    const folded=text.toLowerCase();
    const result=[];
    for(const id of this.groupOrder(this.state)){
      const group=this.state.groups[id];
      const name=typeof group.name==='string'&&group.name?group.name:null;
      if(folded&&(!name||!name.toLowerCase().includes(folded)))continue;
      result.push({
        group_id:id,
        name,
        named:Boolean(name),
        image_keys:uniqueStrings(group.image_keys,value=>typeof value==='string')
      });
    }
    return result;
  }

  mime(key){
    if(typeof key!=='string'||!own(this.state.images,key))throw Error('Unknown image');
    const mime=this.state.images[key].mime;
    if(mime!=='image/png'&&mime!=='image/jpeg')throw Error('Unknown image type');
    return mime;
  }

  image(key){
    if(typeof key!=='string'||!own(this.state.images,key))throw Error('Unknown image');
    const value=this.state.images[key];
    if(typeof value.bytes!=='string')throw Error('Invalid image');
    return Buffer.from(value.bytes,'base64');
  }
}

module.exports={Catalog};
