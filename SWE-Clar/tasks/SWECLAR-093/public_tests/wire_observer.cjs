// Public transport observation, no assertions or private expected values.
const http=require('node:http'),fs=require('node:fs');
const emit=http.Server.prototype.emit;
http.Server.prototype.emit=function(event,...args){
 if((event==='request'||event==='upgrade')&&process.env.SHOP_TRACE){const r=args[0];fs.appendFileSync(process.env.SHOP_TRACE,JSON.stringify({event,method:r.method,path:r.url,time_ms:Date.now()})+'\n');}
 return emit.call(this,event,...args);
};

if(process.env.SHOP_PROCESS_PROOF)fs.writeFileSync(process.env.SHOP_PROCESS_PROOF,JSON.stringify({uid:process.getuid(),status:fs.readFileSync('/proc/self/status','utf8'),environment_keys:Object.keys(process.env)}));
