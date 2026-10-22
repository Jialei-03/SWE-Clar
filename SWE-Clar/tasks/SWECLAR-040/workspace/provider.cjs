const {S3Client,GetObjectCommand,ListObjectsV2Command}=require('@aws-sdk/client-s3');
const {RekognitionClient,IndexFacesCommand,SearchFacesCommand}=require('@aws-sdk/client-rekognition');
class Provider {
 constructor(config){for(const endpoint of [config.s3Endpoint,config.rekognitionEndpoint])if(!['127.0.0.1','localhost','[::1]'].includes(new URL(endpoint).hostname))throw Error('Benchmark endpoints must be loopback');this.config=config;const options={region:'us-east-1',credentials:config.credentials,maxAttempts:1};this.s3=new S3Client({...options,endpoint:config.s3Endpoint,forcePathStyle:true});this.rekognition=new RekognitionClient({...options,endpoint:config.rekognitionEndpoint});}
 async keys(){const found=[],seen=new Set();let token;do{const r=await this.s3.send(new ListObjectsV2Command({Bucket:this.config.bucket,ContinuationToken:token}));for(const row of r.Contents||[])if(typeof row.Key==='string')found.push(row.Key);if(r.IsTruncated&&!r.NextContinuationToken)throw Error('Invalid listing');token=r.IsTruncated?r.NextContinuationToken:undefined;if(token){if(seen.has(token)||seen.size>=100)throw Error('Listing loop');seen.add(token);}}while(token);return [...new Set(found)].sort();}
 async image(key){const r=await this.s3.send(new GetObjectCommand({Bucket:this.config.bucket,Key:key}));const bytes=Buffer.from(await r.Body.transformToByteArray());if(!bytes.length||bytes.length>5000000)throw Error('Invalid image size');if(!bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))&&!(bytes[0]===255&&bytes[1]===216))throw Error('Unsupported image');return bytes;}
 async index(bytes,externalId){throw Error('Implement object indexing');}
 async matches(faceId){throw Error('Implement face search');}
 close(){this.s3.destroy();this.rekognition.destroy();}
}
module.exports={Provider};
