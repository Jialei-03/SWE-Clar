"""Small loopback ComfyUI HTTP client; native server performs validation/execution."""
import json,time,urllib.request,urllib.error,urllib.parse
class ComfyClient:
    def __init__(self,url):
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Use the provided loopback runtime')
        self.url=url.rstrip('/');self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(self,path,body=None):
        request=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=30) as response:return json.load(response)
        except urllib.error.HTTPError as error:raise RuntimeError(error.read().decode()) from None
    def object_info(self):return self.request('/object_info')
    def submit(self,workflow):return self.request('/prompt',workflow)['prompt_id']
    def wait(self,prompt_id,timeout=900):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            record=self.request('/history/'+prompt_id).get(prompt_id)
            if record:
                if record.get('status',{}).get('status_str')=='error':raise RuntimeError(json.dumps(record['status']))
                return record
            time.sleep(.2)
        raise TimeoutError('ComfyUI execution did not finish')
    def image(self,descriptor):
        query=urllib.parse.urlencode({key:descriptor[key] for key in ['filename','subfolder','type'] if key in descriptor})
        with self.opener.open(self.url+'/view?'+query,timeout=30) as response:return response.read()
