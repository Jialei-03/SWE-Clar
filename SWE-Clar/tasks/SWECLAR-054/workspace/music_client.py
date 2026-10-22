class MusicClient:
    def __init__(self,token_url,api_base,client_id,client_secret,redirect_uri):
        self.token_url=token_url;self.api_base=api_base.rstrip('/')
        self.client_id=client_id;self.client_secret=client_secret;self.redirect_uri=redirect_uri
        self._credentials={}
    def authorize_listener(self,listener_id,code):
        raise NotImplementedError("Perform token exchange and profile lookup")
    def save_track(self,listener_id,uri):
        raise NotImplementedError("Send an authenticated library save request")
