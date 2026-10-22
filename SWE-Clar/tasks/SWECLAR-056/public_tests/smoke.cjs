const assert=require('node:assert/strict');const {createHmac}=require('node:crypto');const {WebSocket}=require('ws');
const {startServer}=require(process.cwd()+'/server.cjs');
(async()=>{const secret='public-synthetic-secret';const server=await startServer({secret,port:0});try{
 const response=await fetch(`http://127.0.0.1:${server.port}/health`);assert.equal(response.status,200);assert.equal((await response.json()).ok,true);
 const h=Buffer.from(JSON.stringify({alg:'HS256'})).toString('base64url'),p=Buffer.from(JSON.stringify({sub:'public-user',device_id:'public-device',exp:Date.now()/1000+300})).toString('base64url');const jwt=h+'.'+p+'.'+createHmac('sha256',secret).update(h+'.'+p).digest('base64url');
 const socket=new WebSocket(`ws://127.0.0.1:${server.port}/socket`,{headers:{Authorization:'Bearer '+jwt}});
 const ready=await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(Error('No ready frame')),3000);socket.once('error',reject);socket.once('message',d=>{clearTimeout(timeout);resolve(JSON.parse(d));});});
 assert.equal(ready.type,'ready');assert.equal(ready.device_id,'public-device');assert.equal(typeof ready.connection_id,'string');assert(ready.connection_id);
 socket.terminate();console.log('Health and real signed-token connection baseline passed');
}finally{await server.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
