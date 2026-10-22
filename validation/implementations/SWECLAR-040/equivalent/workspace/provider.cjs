const {S3Client,GetObjectCommand,ListObjectsV2Command}=require('@aws-sdk/client-s3');
const {RekognitionClient,IndexFacesCommand,SearchFacesCommand}=require('@aws-sdk/client-rekognition');
class Provider {
 constructor(config){for(const endpoint of [config.s3Endpoint,config.rekognitionEndpoint])if(!['127.0.0.1','localhost','[::1]'].includes(new URL(endpoint).hostname))throw Error('Benchmark endpoints must be loopback');this.config=config;const options={region:'us-east-1',credentials:config.credentials,maxAttempts:1};this.s3=new S3Client({...options,endpoint:config.s3Endpoint,forcePathStyle:true});this.rekognition=new RekognitionClient({...options,endpoint:config.rekognitionEndpoint});}
 async keys(){
  const found=new Set(),visited=new Set();
  let token;
  while(true){
   if(token!==undefined){
    if(typeof token!=='string'||token.length===0||visited.has(token))throw Error('Listing loop');
    visited.add(token);
   }
   const response=await this.s3.send(new ListObjectsV2Command({Bucket:this.config.bucket,ContinuationToken:token}));
   if(response.Contents!==undefined&&!Array.isArray(response.Contents))throw Error('Invalid listing');
   for(const row of response.Contents||[])if(row&&typeof row.Key==='string')found.add(row.Key);
   if(!response.IsTruncated)break;
   if(typeof response.NextContinuationToken!=='string'||response.NextContinuationToken.length===0)throw Error('Invalid listing');
   token=response.NextContinuationToken;
  }
  return [...found].sort();
 }
 async image(key){const r=await this.s3.send(new GetObjectCommand({Bucket:this.config.bucket,Key:key}));const bytes=Buffer.from(await r.Body.transformToByteArray());if(!bytes.length||bytes.length>5000000)throw Error('Invalid image size');if(!bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))&&!(bytes[0]===255&&bytes[1]===216))throw Error('Unsupported image');return bytes;}
 async index(bytes,externalId){
  if(!Buffer.isBuffer(bytes)||bytes.length===0)throw Error('Invalid image bytes');
  if(typeof externalId!=='string'||!externalId.length)throw Error('Invalid external image ID');
  return this.rekognition.send(new IndexFacesCommand({
   CollectionId:this.config.collection,
   Image:{Bytes:bytes},
   ExternalImageId:externalId,
   DetectionAttributes:['DEFAULT']
  }));
 }
 async matches(faceId){
  if(typeof faceId!=='string'||!faceId.length)throw Error('Invalid face ID');
  return this.rekognition.send(new SearchFacesCommand({
   CollectionId:this.config.collection,
   FaceId:faceId
  }));
 }
 close(){this.s3.destroy();this.rekognition.destroy();}
}
module.exports={Provider};
