import json,math,hashlib
from urllib.request import Request,urlopen
from geometry import point,meters
class GraphClient:
    def __init__(self,url):self.url=url
    def fetch(self,start_node):
        with urlopen(Request(self.url,data=json.dumps({'start_node':start_node}).encode(),headers={'Content-Type':'application/json'},method='POST'),timeout=3) as response:return json.loads(response.read())

def generate_routes(network,start,requested,tolerance):
    return []
