// Public ordinary-user invocation adapter; contains no test inputs or oracle.
const readline=require('node:readline');
const output=process.stdout.write.bind(process.stdout);
console.log=(...args)=>process.stderr.write(args.join(' ')+'\n');
const {startServer}=require(require('node:path').join(process.argv[2],'server.cjs'));
let server,now=1000;
const lines=readline.createInterface({input:process.stdin});let sequence=Promise.resolve();
lines.on('line',line=>{sequence=sequence.then(async()=>{const request=JSON.parse(line);let result;
  try{
    if(request.action==='start'){server=await startServer({secret:request.secret,clock:()=>now,port:0,host:'127.0.0.1'});result={port:server.port};}
    else if(request.action==='time'){now=request.now;result=true;}
    else if(request.action==='snapshot')result=server.snapshot();
    else if(request.action==='sweep')result=server.sweep(request.timeout);
    else if(request.action==='close'){await server.close();result=true;}
    else throw Error('Unknown adapter action');
    output(JSON.stringify({id:request.id,result})+'\n');
  }catch(error){output(JSON.stringify({id:request.id,error:String(error.message)})+'\n');}
});});
lines.on('close',()=>sequence.finally(()=>process.exit()));
