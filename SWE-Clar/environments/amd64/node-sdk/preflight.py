"""Shared image/SDK environment check, independent of candidate code."""
import json,subprocess,sys
base=subprocess.run([sys.executable,'-I','/opt/sweclar/vision_preflight.py'],capture_output=True,text=True,check=True,timeout=90)
check="const s=require('@aws-sdk/client-s3'),r=require('@aws-sdk/client-rekognition');if(!s.S3Client||!r.RekognitionClient)throw Error('Missing SDK');console.log(JSON.stringify({node:process.version,s3:require('@aws-sdk/client-s3/package.json').version,rekognition:require('@aws-sdk/client-rekognition/package.json').version}));"
sdk=subprocess.run(['node','-e',check],capture_output=True,text=True,check=True,timeout=10,user=1000,group=1000,extra_groups=[])
versions=json.loads(sdk.stdout);assert versions['s3']==versions['rekognition']=='3.883.0'
print(json.dumps({'passed':True,'vision':json.loads(base.stdout),'ordinary_user_sdk':versions}))
