const {WebSocket}=require('ws');

const hasOwn=(value,key)=>Object.prototype.hasOwnProperty.call(value,key);

class Broker {
  constructor(clock) {
    this.clock=clock;
    this.records=new Map();
    this.activeByDevice=new Map();
    this.routedMessages=0;
    this.reconnects=0;
  }

  findActive(device) {
    const row=this.activeByDevice.get(device);
    return row && row.active ? row : undefined;
  }

  hasActive(device) {
    return Boolean(this.findActive(device));
  }

  /**
   * Add an authenticated socket to the broker.  A replaced row is never
   * removed from records: it is part of the historical disconnected count.
   */
  attach(socket,claims,id,{reconnect=false,connectedAt}={}) {
    const device=claims.device_id;
    const previous=this.findActive(device);
    let replaced=false;
    if(previous) {
      if(!reconnect) return false;
      this.deactivate(previous,4001,'replaced');
      replaced=true;
    }

    let timestamp=connectedAt;
    if(typeof timestamp!=='number' || !Number.isFinite(timestamp)) timestamp=this.clock();
    const row={
      id,
      socket,
      sub:claims.sub,
      device,
      active:true,
      lastHeartbeat:timestamp
    };
    this.records.set(id,row);
    this.activeByDevice.set(device,row);

    socket.on('error',()=>{});
    socket.on('close',()=>this.onClose(row));
    socket.on('message',data=>this.onMessage(row,data));

    if(!this.send(row,{type:'ready',connection_id:id,device_id:device})) {
      this.deactivate(row,4002,'connection unavailable');
      return false;
    }
    if(replaced) this.reconnects+=1;
    return true;
  }

  onClose(row) {
    row.active=false;
    if(this.activeByDevice.get(row.device)===row) this.activeByDevice.delete(row.device);
  }

  /**
   * Mark a row inactive before asking ws to close it.  Marking first prevents
   * a final frame from a replaced or expired socket from being routed.
   */
  deactivate(row,code=4000,reason='closed',terminate=false) {
    if(!row || !row.active) return false;
    row.active=false;
    if(this.activeByDevice.get(row.device)===row) this.activeByDevice.delete(row.device);

    const socket=row.socket;
    try {
      if(terminate) {
        if(socket.readyState!==WebSocket.CLOSED) socket.terminate();
      } else if(socket.readyState===WebSocket.OPEN) {
        socket.close(code,reason);
      } else if(socket.readyState!==WebSocket.CLOSED) {
        socket.terminate();
      }
    } catch {
      try { socket.terminate(); } catch {}
    }
    return true;
  }

  isLive(row) {
    return row.active &&
      this.records.get(row.id)===row &&
      this.activeByDevice.get(row.device)===row &&
      row.socket.readyState===WebSocket.OPEN;
  }

  send(row,message) {
    if(!row || !row.active || row.socket.readyState!==WebSocket.OPEN) return false;
    try {
      row.socket.send(JSON.stringify(message));
      return true;
    } catch {
      return false;
    }
  }

  sendError(row,code) {
    this.send(row,{type:'error',code});
  }

  onMessage(row,data) {
    // ws can deliver a message immediately before the close event.  Treat a
    // socket that is no longer OPEN as closed for protocol purposes.
    if(!this.isLive(row)) return;

    let message;
    try {
      const text=Buffer.isBuffer(data) ? data.toString('utf8') : String(data);
      message=JSON.parse(text);
    } catch {
      this.sendError(row,'invalid_message');
      return;
    }
    if(!message || typeof message!=='object' || Array.isArray(message)) {
      this.sendError(row,'invalid_message');
      return;
    }

    switch(message.type) {
      case 'heartbeat':
        row.lastHeartbeat=this.clock();
        this.send(row,{type:'heartbeat'});
        break;
      case 'publish':
        this.publish(row,message);
        break;
      case 'status':
        this.send(row,{type:'status',...this.status()});
        break;
      default:
        this.sendError(row,'invalid_message');
        break;
    }
  }

  publish(source,message) {
    if(!hasOwn(message,'target_device') || !hasOwn(message,'payload') ||
       typeof message.target_device!=='string') {
      this.sendError(source,'invalid_message');
      return;
    }

    const target=this.findActive(message.target_device);
    if(!target || !this.isLive(target)) {
      if(target && target.active) this.deactivate(target,4000,'closed');
      this.sendError(source,'target_unavailable');
      return;
    }

    const sequence=this.routedMessages+1;
    const routed=this.send(target,{
      type:'message',
      sequence,
      source_device:source.device,
      target_device:message.target_device,
      payload:message.payload
    });
    if(!routed) {
      this.deactivate(target,4000,'closed');
      this.sendError(source,'target_unavailable');
      return;
    }

    this.routedMessages=sequence;
    this.send(source,{type:'published',sequence});
  }

  sweep(timeout) {
    if(typeof timeout!=='number' || !Number.isFinite(timeout) || timeout<=0) {
      throw new Error('timeout must be a positive finite number');
    }

    const now=this.clock();
    const expired=[];
    for(const row of this.records.values()) {
      if(row.active && now-row.lastHeartbeat>timeout) expired.push(row);
    }
    expired.sort((left,right)=>left.id<right.id ? -1 : left.id>right.id ? 1 : 0);
    for(const row of expired) this.deactivate(row,4000,'heartbeat timeout');
    return expired.map(row=>row.id);
  }

  status() {
    let active=0;
    for(const row of this.records.values()) if(row.active) active+=1;
    return {
      active,
      disconnected:this.records.size-active,
      routed_messages:this.routedMessages,
      reconnects:this.reconnects
    };
  }

  closeAll() {
    for(const row of this.records.values()) {
      if(row.active) this.deactivate(row,1001,'server shutdown',true);
    }
  }
}

module.exports={Broker};
