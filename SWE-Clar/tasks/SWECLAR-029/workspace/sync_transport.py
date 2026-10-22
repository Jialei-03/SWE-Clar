class SyncTransport:
    def __init__(self,endpoint):self.endpoint=endpoint
    def apply(self,entry):raise NotImplementedError()
