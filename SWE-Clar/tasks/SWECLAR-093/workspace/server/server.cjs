const fs=require('node:fs'),http=require('node:http');
const req=require('node:module').createRequire(process.env.SWECLAR_NODE_REQUIRE_ROOT||__filename);
const {WebSocketServer,WebSocket}=req('ws');
const config=JSON.parse(fs.readFileSync(process.env.SHOP_CONFIG,'utf8'));
const subscriptions=new Map(),inboxes=new Map(),carts=new Map(),notifications=new Map(),sockets=new Map();
const own=(object,key)=>typeof key==='string'&&Object.hasOwn(object,key);
function auth(header){if(!header?.startsWith('Bearer '))return null;const id=config.sessions[header.slice(7)];return own(config.users,id)?id:null;}
function cart(user){const rows=[...(carts.get(user)||new Map())].map(([product_id,quantity])=>({product_id,quantity,price_cents:config.products[product_id].price_cents,line_total_cents:quantity*config.products[product_id].price_cents}));return {lines:rows,total_cents:rows.reduce((sum,row)=>sum+row.line_total_cents,0)};}
function action(user,input){const type=input.type;
 if(type==='subscribe'||type==='unsubscribe'){
  const channel=input.channel;if(typeof channel!=='string'||!channel.trim())throw Error('invalid_channel');
  const set=subscriptions.get(user)||new Set();if(type==='subscribe')set.add(channel);else set.delete(channel);subscriptions.set(user,set);return {channels:[...set].sort()};
 }
 if(type==='publish'){
  if(config.users[user].role!=='manager')throw Error('forbidden');
  const {id,channel,title}=input;if(typeof id!=='string'||!id.trim()||typeof channel!=='string'||!channel.trim()||typeof title!=='string'||!title.trim())throw Error('invalid_notification');
  const record={id,channel,title};if(notifications.has(id)){if(JSON.stringify(notifications.get(id))!==JSON.stringify(record))throw Error('notification_conflict');return {duplicate:true};}
  notifications.set(id,record);
  for(const [uid,channels] of subscriptions){if(!channels.has(channel))continue;const rows=inboxes.get(uid)||[];rows.push(record);inboxes.set(uid,rows);for(const socket of sockets.get(uid)||[])if(false)socket.send(JSON.stringify(record));}
  return {duplicate:false};
 }
 if(type==='add'||type==='remove'){
  const id=input.product_id,quantity=input.quantity;if(!own(config.products,id))throw Error('unknown_product');if(!Number.isSafeInteger(quantity)||quantity<=0)throw Error('invalid_quantity');
  const prior=carts.get(user)||new Map(),next=new Map(prior);const old=next.get(id)||0;const count=type==='add'?quantity:0;
  if(!Number.isSafeInteger(count)||!Number.isSafeInteger(count*config.products[id].price_cents))throw Error('invalid_quantity');
  if(count)next.set(id,count);else next.delete(id);
  const total=[...next].reduce((sum,[key,value])=>sum+value*config.products[key].price_cents,0);if(!Number.isSafeInteger(total))throw Error('invalid_quantity');
  carts.set(user,next);return cart(user);
 }
 throw Error('unknown_action');
}
const server=http.createServer(async(request,response)=>{
 const reply=(status,value)=>{const body=JSON.stringify(value);response.writeHead(status,{'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)});response.end(body);};
 const user=auth(request.headers.authorization);if(!user)return reply(401,{error:'unauthenticated'});
 if(request.method==='GET'&&request.url==='/catalog')return reply(200,Object.entries(config.products).map(([id,p])=>({id,...p})));
 if(request.method==='GET'&&request.url==='/inbox')return reply(200,inboxes.get(user)||[]);
 if(request.method==='GET'&&request.url==='/cart')return reply(200,cart(user));
 if(request.method!=='POST'||request.url!=='/actions')return reply(404,{error:'not_found'});
 try {let data='';for await(const chunk of request){data+=chunk;if(data.length>65536)throw Error('invalid_request');}const input=JSON.parse(data);if(!input||typeof input!=='object'||Array.isArray(input))throw Error('invalid_request');reply(200,action(user,input));}catch(error){reply(400,{error:error.message});}
});
const wss=new WebSocketServer({noServer:true});
server.on('upgrade',(request,socket,head)=>{const user=auth(request.headers.authorization);if(!user||request.url!=='/events'){socket.end('HTTP/1.1 401 Unauthorized\r\n\r\n');return;}wss.handleUpgrade(request,socket,head,ws=>{const set=sockets.get(user)||new Set();set.add(ws);sockets.set(user,set);ws.on('close',()=>set.delete(ws));});});
server.listen(Number(process.env.PORT||0),'127.0.0.1',()=>console.log(JSON.stringify({port:server.address().port})));
