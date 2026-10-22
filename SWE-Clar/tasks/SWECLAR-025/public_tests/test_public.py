"""Visible API regressions; no private deletion or report rules."""
import json
from pathlib import Path
import sys
import unittest
import urllib.request
import urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parent))
from inspection_support import Application

class ExistingComponent(unittest.TestCase):
    def setUp(self):
        self.app=Application();self.addCleanup(self.app.close);self.app.start()
    def request(self,command=None,status=200):
        req=urllib.request.Request(self.app.url+('/api/command' if command else '/api/context'),data=json.dumps(command).encode() if command else None,headers={'Authorization':'Bearer demo-inspector','Content-Type':'application/json'})
        try:r=urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5)
        except urllib.error.HTTPError as e:r=e
        with r:
            value=json.load(r);self.assertEqual(r.status,status,value);return value
    def test_context_and_server_address_validation(self):
        before=self.request();self.assertEqual(before['communities']['Example North'],['Oak Lane','Park Way'])
        self.request({'type':'create','id':'public-mismatch','community':'Example North','street':'Cedar Road','residence':'Unit 3'},400)
        self.assertEqual(self.request()['inspections'],before['inspections'])
    def test_valid_creation_and_restart(self):
        action={'type':'create','id':'public-created','community':'Example North','street':'Oak Lane','residence':'Unit 3'}
        self.request(action)
        rows=self.request()['inspections'];self.assertEqual(sum(r['id']==action['id'] and r['status']=='open' for r in rows),1)
        self.app.stop();self.app.start();self.assertEqual(self.request()['inspections'],rows)

if __name__=='__main__':unittest.main()
