const {MongoClient}=require('mongodb');
(async()=>{
 const c=new MongoClient('mongodb://127.0.0.1:27017/?directConnection=true',{serverSelectionTimeoutMS:1000});
 for(let i=0;i<40;i++){try{await c.connect();break;}catch(e){if(i===39)throw e;await new Promise(r=>setTimeout(r,100));}}
 try{
  await c.db('admin').command({replSetInitiate:{_id:'health',members:[{_id:0,host:'127.0.0.1:27017'}]}});
  for(let i=0;i<100;i++){if((await c.db('admin').command({hello:1})).isWritablePrimary)break;if(i===99)throw Error('No primary');await new Promise(r=>setTimeout(r,100));}
  const records=c.db('health').collection('records');await records.insertOne({_id:'retained',value:1});
  const session=c.startSession();
  try{
   await session.withTransaction(async()=>{await records.insertOne({_id:'committed',value:2},{session});});
   try{await session.withTransaction(async()=>{await records.insertOne({_id:'rolled-back',value:3},{session});throw Error('rollback probe');});}catch(e){if(e.message!=='rollback probe')throw e;}
  }finally{await session.endSession();}
  const ids=(await records.find({}).toArray()).map(r=>r._id).sort();if(JSON.stringify(ids)!==JSON.stringify(['committed','retained']))throw Error('Transaction mismatch');
  console.log(JSON.stringify({passed:true,checks:['single-node replica primary','committed transaction','aborted transaction leaves prior records'],ids}));
 }finally{await c.close();}
})().catch(e=>{console.error(e);process.exit(1)});
