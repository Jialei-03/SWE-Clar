const http=require('node:http');
const {WebSocketServer}=require('ws');
const {randomUUID}=require('node:crypto');
const {verifyToken,bearerToken}=require('./auth.cjs');
const {Broker}=require('./broker.cjs');

function rejectUpgrade(socket,status,reason) {
  if(!socket || socket.destroyed) return;
  const body='';
  const response=`HTTP/1.1 ${status} ${reason}\r\nConnection: close\r\nContent-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`;
  try { socket.end(response); } catch { try { socket.destroy(); } catch {} }
}

async function startServer({secret,clock=()=>Date.now()/1000,port=0,host='127.0.0.1'}={}) {
  if(!secret) throw new Error('JWT secret must be configured');
  if(typeof clock!=='function') throw new Error('clock must be a function');

  const broker=new Broker(clock);
  const server=http.createServer((request,response)=>{
    const pathname=(request.url || '').split('?')[0];
    if(pathname==='/health') {
      response.writeHead(200,{'Content-Type':'application/json'});
      response.end('{"ok":true}');
    } else {
      response.writeHead(404);
      response.end();
    }
  });
  const websocket=new WebSocketServer({noServer:true});
  let closePromise;

  server.on('upgrade',(request,socket,head)=>{
    let claims;
    let authenticatedAt;
    try {
      const token=bearerToken(request.headers.authorization);
      authenticatedAt=clock();
      claims=verifyToken(token,secret,authenticatedAt);
    } catch {
      rejectUpgrade(socket,401,'Unauthorized');
      return;
    }

    let url;
    try { url=new URL(request.url || '/',`http://${request.headers.host || 'localhost'}`); }
    catch {
      rejectUpgrade(socket,400,'Bad Request');
      return;
    }
    const reconnect=url.searchParams.get('mode')==='reconnect';
    if(broker.hasActive(claims.device_id) && !reconnect) {
      rejectUpgrade(socket,409,'Conflict');
      return;
    }

    try {
      websocket.handleUpgrade(request,socket,head,ws=>{
        const attached=broker.attach(ws,claims,randomUUID(),{reconnect,connectedAt:authenticatedAt});
        // The admission check above is synchronous with handleUpgrade.  This
        // fallback only protects against a socket becoming unusable during
        // the handshake; an ordinary duplicate has already received 409.
        if(!attached) {
          try { ws.terminate(); } catch {}
        }
      });
    } catch {
      try { socket.destroy(); } catch {}
    }
  });

  await new Promise((resolve,reject)=>{
    const onError=error=>{server.removeListener('listening',resolve);reject(error);};
    server.once('error',onError);
    server.once('listening',resolve);
    server.listen(port,host);
  });

  const address=server.address();
  const actualPort=address && typeof address==='object' ? address.port : port;
  return {
    port:actualPort,
    sweep:timeout=>broker.sweep(timeout),
    snapshot:()=>broker.status(),
    close:()=>{
      if(closePromise) return closePromise;
      closePromise=new Promise(resolve=>{
        broker.closeAll();
        for(const client of websocket.clients) {
          try { client.terminate(); } catch {}
        }

        let serverDone=false;
        let websocketDone=false;
        const finish=()=>{
          if(serverDone && websocketDone) resolve();
        };
        try {
          server.close(()=>{serverDone=true;finish();});
        } catch { serverDone=true; }
        try {
          websocket.close(()=>{websocketDone=true;finish();});
        } catch { websocketDone=true; }
        finish();
      });
      return closePromise;
    }
  };
}

module.exports={startServer};
if(require.main===module) startServer({secret:process.env.JWT_SECRET,port:Number(process.env.PORT || 8080)})
  .then(server=>console.log(JSON.stringify({port:server.port})))
  .catch(error=>{console.error(error.message);process.exitCode=1;});
