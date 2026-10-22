class Broker {
  constructor(clock) {this.clock=clock;this.records=new Map();}
  hasActive(device) {return [...this.records.values()].some(row=>row.device===device && row.active);}
  attach(socket,claims,id) {
    const row={socket,device:claims.device_id,active:true};this.records.set(id,row);
    socket.send(JSON.stringify({type:'ready',connection_id:id,device_id:row.device}));
    socket.on('close',()=>{row.active=false;});
    socket.on('message',buffer=>socket.send(JSON.stringify({type:'echo',text:buffer.toString()})));
  }
  sweep(timeout) {return [];}
  status() {const active=[...this.records.values()].filter(row=>row.active).length;
    return {active,disconnected:this.records.size-active,routed_messages:0,reconnects:0};}
}
module.exports={Broker};
