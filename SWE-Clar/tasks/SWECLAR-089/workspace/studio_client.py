import json
from urllib.parse import quote,urlsplit
from urllib.request import Request,urlopen
class StudioClient:
    def __init__(self,base_url,token=None):self.base=base_url.rstrip('/');self.token=token
    def request(self,method,path,body=None,key=None):
        headers={'Content-Type':'application/json'}
        if self.token:headers['Authorization']='Bearer '+self.token
        if key:headers['Idempotency-Key']=key
        with urlopen(Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers=headers),timeout=3) as response:
            if not 200<=response.status<300:raise ValueError('provider failed')
            return json.loads(response.read())
    def payment(self,event_id):
        if not isinstance(event_id,str) or not event_id.strip():raise ValueError('invalid event')
        return self.request('GET','/payments/'+quote(event_id,safe=''))
    def meeting(self,bid,student,instructor,slot):raise NotImplementedError('Create meeting through provider')
    def email(self,event_id,payload):raise NotImplementedError('Submit notification')
