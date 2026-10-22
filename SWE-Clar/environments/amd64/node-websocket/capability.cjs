const assert=require('node:assert/strict');const {WebSocketServer,WebSocket}=require('ws');
(async()=>{assert.equal(process.getuid(),1000);assert.equal(require('ws/package.json').version,'8.19.0');assert.equal(process.version,'v22.18.0');
const server=new WebSocketServer({host:'127.0.0.1',port:0});await new Promise(r=>server.once('listening',r));server.on('connection',s=>s.on('message',d=>s.send(d)));
const socket=new WebSocket(`ws://127.0.0.1:${server.address().port}`);const roundtrip=new Promise((resolve,reject)=>{socket.once('error',reject);socket.once('message',data=>{assert.equal(data.toString(),'capability-roundtrip');resolve();});});
await new Promise(r=>socket.once('open',r));socket.send('capability-roundtrip');await roundtrip;socket.terminate();for(const c of server.clients)c.terminate();await new Promise(r=>server.close(r));console.log(JSON.stringify({passed:true,node:process.version,ws:require('ws/package.json').version,uid:process.getuid(),real_loopback_roundtrip:true}));
})().catch(e=>{console.error(e);process.exit(1)});
