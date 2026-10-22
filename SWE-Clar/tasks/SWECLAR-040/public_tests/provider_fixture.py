"""Public SDK-compatible fixture with generated geometry; not a recognition model."""
import base64,hashlib,io,json,sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlsplit,unquote
from PIL import Image,ImageDraw

images={}
for number,color in enumerate(['navy','orange','green'],1):
    picture=Image.new('RGB',(40,32),'white');ImageDraw.Draw(picture).rectangle((number,4,25,24),fill=color)
    buffer=io.BytesIO();picture.save(buffer,format='PNG');images[f'geometry-{number}.png']=buffer.getvalue()
def face_id(key):
    value=hashlib.sha256(key.encode()).hexdigest()[:32]
    return '-'.join([value[:8],value[8:12],value[12:16],value[16:20],value[20:]])
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,mime,body):
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def payload(self,value,status=200):self.send(status,'application/x-amz-json-1.1',json.dumps(value).encode())
    def authorized(self):return self.headers.get('Authorization','').startswith('AWS4-HMAC-SHA256 ')
    def do_GET(self):
        parsed=urlsplit(self.path);query=parse_qs(parsed.query)
        if parsed.path=='/health':return self.payload({'ready':True,'synthetic_assets':len(images)})
        if not self.authorized():return self.payload({'error':'SDK authorization header required'},403)
        if 'list-type' in query:
            second='continuation-token' in query;keys=sorted(images)[2:] if second else sorted(images)[:2]
            xml='<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>synthetic-images</Name><IsTruncated>'+str(not second).lower()+'</IsTruncated>'
            if not second:xml+='<NextContinuationToken>page-2</NextContinuationToken>'
            xml+=''.join('<Contents><Key>'+key+'</Key></Contents>' for key in keys)+'</ListBucketResult>'
            return self.send(200,'application/xml',xml.encode())
        key=unquote(parsed.path.removeprefix('/synthetic-images/'))
        if key not in images:return self.send(404,'application/xml',b'<Error><Code>NoSuchKey</Code></Error>')
        self.send(200,'image/png',images[key])
    def do_POST(self):
        if not self.authorized():return self.payload({'error':'SDK authorization header required'},403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=5000000:raise ValueError('Invalid request length')
            data=json.loads(self.rfile.read(size));kind=self.headers.get('X-Amz-Target','').split('.')[-1]
            if data.get('CollectionId')!='synthetic-collection':raise ValueError('Unknown collection')
            if kind=='IndexFaces':
                raw=base64.b64decode(data.get('Image',{}).get('Bytes',''),validate=True)
                key=next((key for key,value in images.items() if value==raw),None)
                if key is None or not data.get('ExternalImageId'):raise ValueError('Supply prepared image bytes and external ID')
                return self.payload({'FaceRecords':[{'Face':{'FaceId':face_id(key)}}]})
            if kind=='SearchFaces':
                ident=data.get('FaceId')
                if ident not in [face_id(k) for k in images]:raise ValueError('Unknown face')
                return self.payload({'FaceMatches':[{'Face':{'FaceId':ident},'Similarity':100}]})
            raise ValueError('Unsupported SDK operation')
        except (ValueError,TypeError,KeyError):self.payload({'__type':'InvalidParameterException','message':'Invalid fixture request'},400)

if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    (Path(sys.argv[1])/'ready.json').write_text(json.dumps({'url':f'http://127.0.0.1:{server.server_port}'}))
    server.serve_forever()
