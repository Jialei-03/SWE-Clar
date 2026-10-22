"""Public HTTP/service fixtures; no private business policies or answers."""
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
sys.path.insert(0,'/opt/sweclar')
from harness import App, CandidateFailure
from offer_service import OfferService

PROJECT=Path(os.environ.get('SWECLAR_PROJECT_DIR','/workspace'))


class Workspace:
    def __init__(self, events=(), *, webhooks=False):
        self.peer=OfferService(events,webhook_supported=webhooks)
        self.app=App(PROJECT,['--offer-service',self.peer.url])

    def __enter__(self):
        self.peer.__enter__()
        try:self.app.start()
        except BaseException:
            self.__exit__(None,None,None)
            raise
        return self

    def __exit__(self,*_):
        try:self.app.__exit__(None,None,None)
        finally:self.peer.__exit__(None,None,None)

    def restart(self):
        self.app.stop();self.app.start()

    def request(self,path,body=None,*,actor='seller-a',method=None,status=200):
        request=Request(self.app.url+path,data=json.dumps(body).encode() if body is not None else None,
                        headers={'Content-Type':'application/json','X-Actor':actor},method=method)
        try:response=urlopen(request,timeout=6)
        except HTTPError as error:response=error
        except (URLError,TimeoutError,ConnectionError) as error:raise CandidateFailure('Application HTTP failure') from error
        with response:
            text=response.read().decode()
            if response.status!=status:raise CandidateFailure(f'{path}: expected {status}, received {response.status}: {text[:250]}')
        try:data=json.loads(text)
        except ValueError as error:raise CandidateFailure('Application returned invalid JSON') from error
        if not isinstance(data,dict):raise CandidateFailure('Application response must be a JSON object')
        if status >= 400:
            assert isinstance(data.get('errors'),dict), 'Error response must contain errors object'
        else:
            for key in ['listings','offers','notifications','actors']:
                if key in data:
                    assert isinstance(data[key],list) and all(isinstance(x,dict) for x in data[key]), key+' must be an object list'
            if 'listing' in data:
                assert isinstance(data['listing'],dict) and {'id','owner_id','agent_id','label','property_type','bedrooms','bathrooms','floor_area','asking_price','features','state'} <= data['listing'].keys(), 'Malformed listing'
            if 'pricing' in data and data['pricing'] is not None:
                price=data['pricing']
                assert isinstance(price,dict) and {'minimum','midpoint','maximum','confidence','comparable_ids','adjusted_prices'} <= price.keys(), 'Malformed pricing object'
            if 'descriptions' in data:
                assert isinstance(data['descriptions'],list) and all(isinstance(x,str) for x in data['descriptions']), 'Malformed description list'
        return data


def event(revision=1,**values):
    return {'cursor':revision,'external_id':'offer-a','listing_id':'parcel-a','revision':revision,'amount':190000+revision,'terms':'Synthetic terms',**values}


def draft(**values):
    return {'label':'Synthetic new parcel','property_type':'house','bedrooms':3,'bathrooms':2,'floor_area':100,'asking_price':200000,'features':['courtyard'],**values}
