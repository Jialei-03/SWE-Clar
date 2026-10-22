// Exercise SDK/toolchain independently of incomplete indexing business code.
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {S3Client,GetObjectCommand,ListObjectsV2Command}=require('@aws-sdk/client-s3');
const {RekognitionClient,IndexFacesCommand,SearchFacesCommand}=require('@aws-sdk/client-rekognition');
(async()=>{
  const root=process.argv[2]||'/workspace';const cfg=JSON.parse(fs.readFileSync(root+'/runtime/config.json'));
  const options={region:'us-east-1',credentials:cfg.credentials,maxAttempts:1};
  const s3=new S3Client({...options,endpoint:cfg.s3Endpoint,forcePathStyle:true});
  const recognition=new RekognitionClient({...options,endpoint:cfg.rekognitionEndpoint});
  try {
    const first=await s3.send(new ListObjectsV2Command({Bucket:cfg.bucket}));assert.ok(first.IsTruncated);
    const second=await s3.send(new ListObjectsV2Command({Bucket:cfg.bucket,ContinuationToken:first.NextContinuationToken}));
    assert.equal(first.Contents.length+second.Contents.length,3);
    const object=await s3.send(new GetObjectCommand({Bucket:cfg.bucket,Key:first.Contents[0].Key}));
    const bytes=Buffer.from(await object.Body.transformToByteArray());assert.ok(bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])));
    const indexed=await recognition.send(new IndexFacesCommand({CollectionId:cfg.collection,Image:{Bytes:bytes},ExternalImageId:crypto.createHash('sha256').update(bytes).digest('hex'),DetectionAttributes:['DEFAULT']}));
    const found=await recognition.send(new SearchFacesCommand({CollectionId:cfg.collection,FaceId:indexed.FaceRecords[0].Face.FaceId}));assert.ok(found.FaceMatches.length);
    console.log(JSON.stringify({passed:true,paginated_sdk_listing:true,actual_image_bytes:true,index_and_search_transport:true,business_rules:'not established by public smoke'}));
  } finally {s3.destroy();recognition.destroy();}
})().catch(error=>{console.error(error);process.exitCode=1;});
