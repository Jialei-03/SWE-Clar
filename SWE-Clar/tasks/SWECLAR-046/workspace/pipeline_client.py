import json
from urllib.parse import quote
from urllib.request import Request,urlopen

class PipelineClient:
    def __init__(self,source_urls,destination_urls,outreach_url,token=None):
        self.source_urls=source_urls;self.destination_urls=destination_urls;self.outreach_url=outreach_url;self.token=token
    def request(self,method,url,body=None,key=None):
        headers={'Content-Type':'application/json'}
        if self.token:headers['Authorization']='Bearer '+self.token
        if key:headers['Idempotency-Key']=key
        request=Request(url,data=json.dumps(body).encode() if body is not None else None,method=method,headers=headers)
        with urlopen(request,timeout=5) as response:
            if not 200<=response.status<300:raise ValueError('service rejected request')
            return json.loads(response.read())
    def read_source(self,name):return self.request('GET',self.source_urls[name])
    def read_destination(self,name):return self.request('GET',self.destination_urls[name])
    def upsert(self,destination,source_id,row):raise NotImplementedError("Send the destination write")
    def submit_outreach(self,delivery_id,email):raise NotImplementedError("Send the outreach request")
