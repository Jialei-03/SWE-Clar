const assert=require('node:assert/strict');
const path=require('node:path');
const {createRequire}=require('node:module');
const {createHmac,randomBytes}=require('node:crypto');
let WebSocket;
try {WebSocket=require('ws');require('node:fs').accessSync('/public_tests/server_worker.cjs');}
catch(error){console.log(JSON.stringify({results:[],harness_ok:false,infrastructure_error:true,infrastructure_errors:[String(error)]}));process.exit(2);}
const root=path.resolve(process.env.TARGET_ROOT || '.');
const secret=randomBytes(32).toString('hex');
const results=[];
function fields(actual,expected){for(const [key,value] of Object.entries(expected))assert.deepEqual(actual[key],value);}
function token(device,options={}) {
  const header=Buffer.from(JSON.stringify({alg:options.alg || 'HS256',typ:'JWT'})).toString('base64url');
  const payload=Buffer.from(JSON.stringify({sub:'synthetic-user',device_id:device,exp:2000,...options.claims})).toString('base64url');
  const signature=createHmac('sha256',options.secret || secret).update(header+'.'+payload).digest('base64url');
  return header+'.'+payload+'.'+signature;
}
async function connect(server,jwt,mode='connect',authorization='Bearer '+jwt) {
  const socket=new WebSocket(`ws://127.0.0.1:${server.port}/socket?mode=${mode}`,{headers:authorization===null?{}:{Authorization:authorization}});
  const queue=[];const waiters=[];
  socket.on('error',()=>{});
  socket.on('message',raw=>{let value;try{value=JSON.parse(raw.toString());}catch{value={invalid:raw.toString()};}
    if(waiters.length)waiters.shift()(value);else queue.push(value);});
  const next=()=>queue.length ? Promise.resolve(queue.shift()) : new Promise((resolve,reject)=>{
    const deliver=value=>{clearTimeout(timer);resolve(value);};
    const timer=setTimeout(()=>{const i=waiters.indexOf(deliver);if(i>=0)waiters.splice(i,1);reject(new Error('no expected frame delivered'));},1200);
    waiters.push(deliver);
  });
  const opened=await new Promise(resolve=>{
    const timer=setTimeout(()=>{socket.terminate();resolve({status:'timeout'});},1500);
    socket.once('open',()=>{clearTimeout(timer);resolve({status:101});});
    socket.once('unexpected-response',(_,response)=>{clearTimeout(timer);response.resume();socket.terminate();resolve({status:response.statusCode});});
    socket.once('error',()=>{clearTimeout(timer);resolve({status:'error'});});
  });
  return {...opened,socket,next,queue,send:value=>socket.send(JSON.stringify(value))};
}
async function fixture(fn) {
  let now=1000;
  const {createServer}=require('./server_proxy.cjs');
  const server=await createServer(root,secret);
  try {await fn(server,value=>server.setTime(value));} finally {await server.close();}
}
async function gate(id,fn) {try{await fixture(fn);results.push({ru_id:id,passed:true});}
  catch(error){results.push({ru_id:id,passed:false,details:{error:String(error.stack || error)}});}}
(async()=>{
  await gate('RU-001',async server=>{
    const health=await fetch(`http://127.0.0.1:${server.port}/health`);assert.equal(health.status,200);assert.equal((await health.json()).ok,true);
    const a=await connect(server,token('device-a'));assert.equal(a.status,101);
    const ready=await a.next();assert.equal(ready.type,'ready');assert.equal(ready.device_id,'device-a');assert.equal(typeof ready.connection_id,'string');assert(ready.connection_id);
    for(const invalid of [null,[],"not an object"]) {a.send(invalid);assert.equal((await a.next()).error.code,'invalid_message');}
    a.socket.send('{malformed');assert.equal((await a.next()).error.code,'invalid_message');
    assert.equal((await fetch(`http://127.0.0.1:${server.port}/health`)).status,200);
  });
  await gate('RU-002',async server=>{
    const before=await server.snapshot();
    for(const key of ['sub','device_id'])for(const value of [123,true,[],['sensor'],{}]) {
      const bad=await connect(server,token('typed-identity',{claims:{[key]:value}}));
      assert.equal(bad.status,401,'identity claims must be nonempty strings');
      fields(await server.snapshot(),Object.fromEntries(['active','disconnected','routed_messages','reconnects'].map(k=>[k,before[k]])));
    }
    for(const jwt of [token('forged',{secret:'wrong-test-signing-key'}),token('expired',{claims:{exp:1000}}),token('empty',{claims:{sub:''}}),token('empty',{claims:{device_id:''}}),token('none',{alg:'none'}),token('bad-exp',{claims:{exp:'2000'}}),token('boolean',{claims:{exp:true}}),token('unsigned').split('.').slice(0,2).join('.')+'.','malformed']) {
      const bad=await connect(server,jwt);assert.equal(bad.status,401,'invalid JWT must not upgrade');
    }
    for(const authorization of [null,'Basic '+token('bad-scheme')])assert.equal((await connect(server,token('bad-scheme'),'connect',authorization)).status,401);
    assert.equal((await server.snapshot()).active,0);
    const a=await connect(server,token('same-device'));assert.equal(a.status,101);await a.next();
    const duplicate=await connect(server,token('same-device'));assert.equal(duplicate.status,409);
    assert.equal((await server.snapshot()).active,1);
  });
  await gate('RU-003',async server=>{
    const a=await connect(server,token('reconnect-device'));const first=await a.next();
    const closed=new Promise(resolve=>a.socket.once('close',resolve));
    const b=await connect(server,token('reconnect-device'),'reconnect');assert.equal(b.status,101);const second=await b.next();
    assert.equal(second.device_id,first.device_id);assert.notEqual(second.connection_id,first.connection_id);
    await Promise.race([closed,new Promise((_,reject)=>setTimeout(()=>reject(new Error('old connection remains open')),1200))]);
    fields((await server.snapshot()),{active:1,disconnected:1,routed_messages:0,reconnects:1});
  });
  await gate('RU-004',async(server,time)=>{
    const stale=await connect(server,token('stale'));const staleReady=await stale.next();
    const fresh=await connect(server,token('fresh'));await fresh.next();
    await time(1005);fresh.send({type:'heartbeat'});assert.equal((await fresh.next()).type,'heartbeat');
    await time(1010);assert.deepEqual((await server.sweep(10)),[],'boundary is strictly greater');
    const staleClosed=new Promise(resolve=>stale.socket.once('close',resolve));
    await time(1011);assert.deepEqual((await server.sweep(10)),[staleReady.connection_id]);
    await Promise.race([staleClosed,new Promise((_,reject)=>setTimeout(()=>reject(Error('Stale socket not closed')),1200))]);
    fields((await server.snapshot()),{active:1,disconnected:1,routed_messages:0,reconnects:0});
    let rejected=false;try{const invalid=await server.sweep(0);rejected=!!(invalid&&invalid.error);}catch{rejected=true;}assert(rejected,'invalid timeout must report an error');
    fresh.send({type:'heartbeat'});assert.equal((await fresh.next()).type,'heartbeat');
  });
  await gate('RU-005',async server=>{
    const a=await connect(server,token('source'));await a.next();const b=await connect(server,token('target'));await b.next();
    const payload={text:'synthetic payload',nested:[1,true,null,{value:'unchanged'}]};
    for(let sequence=1;sequence<=2;sequence++) {
      a.send({type:'publish',target_device:'target',payload});
      fields(await b.next(),{type:'message',sequence,source_device:'source',target_device:'target',payload});
      fields(await a.next(),{type:'published',sequence});
    }
    a.send({type:'publish',target_device:'missing',payload});assert.equal((await a.next()).error.code,'target_unavailable');
    a.send({type:'status'});fields(await a.next(),{type:'status',active:2,disconnected:0,routed_messages:2,reconnects:0});
    // The following target frame must be its status response, not a duplicate delivery.
    b.send({type:'status'});assert.equal((await b.next()).type,'status');
    await new Promise(resolve=>{b.socket.once('close',resolve);b.socket.close();});
    await new Promise(resolve=>setImmediate(resolve));
    a.send({type:'publish',target_device:'target',payload});assert.equal((await a.next()).error.code,'target_unavailable');
    assert.equal((await server.snapshot()).routed_messages,2);
  });
  console.log(JSON.stringify({results,harness_ok:true},null,2));
  if(results.some(x=>!x.passed))process.exitCode=1;
})();
