const {spawn}=require('node:child_process');
const readline=require('node:readline');
async function createServer(root,secret){
 const child=spawn(process.execPath,['/public_tests/server_worker.cjs',root],{uid:1000,gid:1000,cwd:root,env:{PATH:process.env.PATH,NODE_PATH:process.env.NODE_PATH,HOME:'/tmp'},stdio:['pipe','pipe','pipe']});
 let id=0,errors='';const waiting=new Map();child.stderr.on('data',d=>{errors+=d;});
 readline.createInterface({input:child.stdout}).on('line',line=>{let value;try{value=JSON.parse(line);}catch{return;}
  const waiter=waiting.get(value.id);if(!waiter)return;waiting.delete(value.id);clearTimeout(waiter.timer);if(value.error)waiter.reject(Error(value.error));else waiter.resolve(value.result);});
 child.on('exit',()=>{for(const w of waiting.values()){clearTimeout(w.timer);w.reject(Error('Candidate exited: '+errors.slice(-500)));}waiting.clear();});
 function rpc(action,extra={}){return new Promise((resolve,reject)=>{const key=++id;const timer=setTimeout(()=>{waiting.delete(key);child.kill('SIGKILL');reject(Error('Candidate control timeout'));},6000);waiting.set(key,{resolve,reject,timer});child.stdin.write(JSON.stringify({id:key,action,...extra})+'\n');});}
 try{const info=await rpc('start',{secret});return {port:info.port,snapshot:()=>rpc('snapshot'),sweep:timeout=>rpc('sweep',{timeout}),setTime:now=>rpc('time',{now}),close:async()=>{try{await rpc('close');}finally{child.stdin.end();child.kill();}}};}
 catch(error){child.kill();throw error;}
}
module.exports={createServer};
