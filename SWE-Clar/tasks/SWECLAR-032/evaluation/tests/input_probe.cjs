// Runs as the ordinary candidate identity; management compares the returned object.
const {MongoClient}=require('mongodb');
(async()=>{
 let input='';for await(const chunk of process.stdin)input+=chunk;const p=JSON.parse(input);
 const c=new MongoClient(p.uri);await c.connect();
 try{
  const {Portal}=require(p.project+'/portal.cjs');
  const portal=new Portal(c,c.db(p.database),{});
  const session=await portal.session(p.token);
  try{await portal.migrate(session,p.rows);}catch(e){/* RU002 independently requires successful valid migration. */}
  console.log(JSON.stringify({rows:p.rows,session}));
 }finally{await c.close();}
})().catch(e=>{console.error(e.message);process.exit(1)});
