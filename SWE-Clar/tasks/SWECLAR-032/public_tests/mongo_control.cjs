// Benchmark management CLI; credentials arrive only through its private stdin.
const {MongoClient}=require('mongodb');
(async()=>{
 let text='';for await(const chunk of process.stdin)text+=chunk;const input=JSON.parse(text);
 const c=new MongoClient(input.uri,{directConnection:input.operation==='initialize',serverSelectionTimeoutMS:1000});
 try{
  for(let i=0;i<50;i++){try{await c.connect();break;}catch(e){if(i===49)throw e;await new Promise(r=>setTimeout(r,100));}}
  if(input.operation==='initialize'){
   await c.db('admin').command({replSetInitiate:{_id:'sweclar_fixture',members:[{_id:0,host:input.host}]}});
   for(let i=0;i<100;i++){if((await c.db('admin').command({hello:1})).isWritablePrimary)break;if(i===99)throw Error('Replica primary unavailable');await new Promise(r=>setTimeout(r,100));}
   await c.db('admin').command({createUser:'manager',pwd:input.password,roles:['root']});
  }else if(input.operation==='provision'){
   await c.db(input.database).command({createUser:'candidate',pwd:input.password,roles:[{role:'readWrite',db:input.database}]});
  }else throw Error('Unknown management operation');
  console.log(JSON.stringify({passed:true}));
 }finally{await c.close();}
})().catch(e=>{console.error(e.codeName||'Mongo management operation failed');process.exit(1)});
