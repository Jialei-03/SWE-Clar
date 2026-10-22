const http=require('node:http');
const {WebSocketServer}=require('ws');
const {randomUUID}=require('node:crypto');
const {verifyToken}=require('./auth.cjs');
const {Broker}=require('./broker.cjs');

async function startServer({secret,clock=()=>Date.now()/1000,port=0,host='127.0.0.1'}) {
  if(!secret) throw new Error('JWT secret must be configured');
  const broker=new Broker(clock);
  const server=http.createServer((request,response)=>{
    if(request.url==='/health') {response.writeHead(200,{'Content-Type':'application/json'});response.end('{"ok":true}');}
    else {response.writeHead(404);response.end();}
  });
  const websocket=new WebSocketServer({noServer:true});
  server.on('upgrade',(request,socket,head)=>{
    const url=new URL(request.url,'http://localhost');
    let claims;
    try {claims=verifyToken((request.headers.authorization || '').replace(/^Bearer /,''),secret,clock());}
    catch {socket.end('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');return;}
    const reconnect=url.searchParams.get('mode')==='reconnect';
    if(broker.hasActive(claims.device_id) && !reconnect) {socket.end('HTTP/1.1 409 Conflict\r\nConnection: close\r\n\r\n');return;}
    websocket.handleUpgrade(request,socket,head,ws=>broker.attach(ws,claims,randomUUID(),reconnect));
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,host,resolve);});
  return {port:server.address().port, sweep:timeout=>broker.sweep(timeout), snapshot:()=>broker.status(),
    close:async()=>{for(const client of websocket.clients)client.terminate();await new Promise(resolve=>server.close(resolve));websocket.close();}};
}
module.exports={startServer};
if(require.main===module) startServer({secret:process.env.JWT_SECRET,port:Number(process.env.PORT || 8080)})
  .then(server=>console.log(JSON.stringify({port:server.port}))).catch(error=>{console.error(error.message);process.exitCode=1;});
