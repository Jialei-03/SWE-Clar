"""Public regressions for the existing HTTP component; run from project root."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parent))
from stream_support import Application


class ExistingWebsite(unittest.TestCase):
    def setUp(self):
        self.app = Application()
        self.addCleanup(self.app.close)
        self.app.start()
        self.base = self.app.url
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self,path,body=None,admin=False,status=200):
        headers = {'Content-Type':'application/json'}
        if admin:headers['Authorization']='Bearer demo-admin'
        req = urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:response=self.http.open(req,timeout=10)
        except urllib.error.HTTPError as error:response=error
        with response:
            data=response.read()
            self.assertEqual(response.status,status,(path,data[:200]))
            return json.loads(data) if 'application/json' in response.headers.get('Content-Type','') else data

    def create(self,ident,**updates):
        body={'event_id':ident,'title':'Synthetic '+ident,'start':'2035-01-01T08:00:00+08:00','end':'2035-01-01T01:00:00Z'}
        body.update(updates)
        return self.request('/event',body,admin=True)

    def test_site_and_management_authentication(self):
        self.assertIn(b'<html',self.request('/'))
        self.assertTrue(self.request('/app.js'))
        self.request('/event',{},status=403)
        self.create('alpha')
        self.request('/event',{'event_id':'beta','title':'No timezone','start':'2035-01-01T00:00:00','end':'2035-01-01T01:00:00'},admin=True,status=400)
        self.assertEqual(len(self.request('/calendar?now=2034-01-01T00:00:00Z')),1)

    def test_calendar_instants_order_and_cancellation(self):
        self.create('beta')
        self.create('alpha',start='2035-01-01T00:00:00Z')
        rows=self.request('/calendar?now=2035-01-01T00:00:00Z')
        self.assertEqual([r['event_id'] for r in rows],['alpha','beta'])
        self.request('/cancel',{'event_id':'alpha'},admin=True)
        rows=self.request('/calendar?now=2035-01-01T00:00:00Z')
        self.assertEqual([r['event_id'] for r in rows],['beta'])
        self.assertEqual(self.request('/calendar?now=2035-01-01T00:00:00.001Z'),[])


if __name__ == '__main__':
    unittest.main()
