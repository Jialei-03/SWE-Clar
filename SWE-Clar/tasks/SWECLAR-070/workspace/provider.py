import json,math
from urllib.request import build_opener,ProxyHandler
from urllib.parse import urlencode,urlsplit

def number(value,low,high):
    if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or not low<=value<=high:raise ValueError('invalid_number')
    return value

def location(p):return {'latitude':number(p['latitude'],-90,90),'longitude':number(p['longitude'],-180,180)}
class SolarClient:
    def __init__(self,config):
        self.config=config
        for name in ['geocoding_url','solar_url']:
            if urlsplit(config[name]).hostname not in ['127.0.0.1','localhost','::1']:raise ValueError('benchmark_endpoint_must_be_local')
    def get(self,url,params):
        with build_opener(ProxyHandler({})).open(url+'?'+urlencode({**params,'key':self.config['api_key']}),timeout=3) as response:return json.loads(response.read())
    def find(self,address):raise NotImplementedError('Resolve address and retrieve actual roof data')
