from pathlib import Path
class OfflineStore:
    def __init__(self,root,key):self.root=Path(root);self.key=key
    def write_bundle(self,user_id,job_id,data):raise NotImplementedError()
    def read_bundle(self,user_id,job_id):raise NotImplementedError()
    def remove_user(self,user_id):raise NotImplementedError()
