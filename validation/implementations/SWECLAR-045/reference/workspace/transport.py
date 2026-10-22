import json
from urllib.request import Request,urlopen

def upload_events(url,events):
    request=Request(url,data=json.dumps({'events':events}).encode(),headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=5) as response:return json.load(response)
