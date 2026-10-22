import base64,json
from urllib.parse import urlencode
from urllib.request import Request,urlopen

class SmartlinkClient:
    def __init__(self,token_url,profile_url,client_id,client_secret,redirect_uri,conversion_urls=None):
        self.token_url=token_url;self.profile_url=profile_url;self.client_id=client_id
        self.client_secret=client_secret;self.redirect_uri=redirect_uri;self.conversion_urls=conversion_urls or {}
    def authorize(self,code):
        raise NotImplementedError("Complete the provider HTTP authorization")
    def send_conversion(self,platform,payload,key):
        raise NotImplementedError("Complete the outbound connector")
