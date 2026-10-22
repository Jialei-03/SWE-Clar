import json
from urllib.request import Request,urlopen
class TranslationClient:
    def __init__(self,url):self.url=url
    def translate(self,text,language):raise NotImplementedError('Call translation provider')
