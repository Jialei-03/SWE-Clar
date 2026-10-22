const fs=require('node:fs/promises'),crypto=require('node:crypto'),path=require('node:path');
const clone=x=>structuredClone(x);
class Catalog {
 constructor(file,provider){this.file=file;this.provider=provider;this.state={images:{},faces:{},groups:{},nextGroup:1};}
 async load(){try{this.state=JSON.parse(await fs.readFile(this.file,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}}
 async commit(next){await fs.mkdir(path.dirname(this.file),{recursive:true});const temp=this.file+'.pending';try{await fs.writeFile(temp,JSON.stringify(next));await fs.rename(temp,this.file);this.state=next;}finally{await fs.rm(temp,{force:true});}}
 async ingest(key){throw Error('Implement image indexing and grouping');}
 async scan(){const keys=await this.provider.keys();const results=[];for(const key of keys)results.push({key,...await this.ingest(key)});return {images:results};}
 async label(id,name){throw Error('Implement group naming');}
 list(query=''){return [];}
 mime(key){if(!Object.hasOwn(this.state.images,key))throw Error('Unknown image');return this.state.images[key].mime;}
 image(key){const item=Object.hasOwn(this.state.images,key)?this.state.images[key]:null;if(!item)throw Error('Unknown image');return Buffer.from(item.bytes,'base64');}
}
module.exports={Catalog};
