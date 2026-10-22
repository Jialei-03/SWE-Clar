"""Benchmark-owned web and live synthetic-offer capability preparation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path('/opt/sweclar')
sys.path.insert(0,str(ROOT))
from web_preflight import preflight as web_preflight
from offer_service import OfferService


def ready():
    try:
        with urlopen('http://127.0.0.1:38900/health', timeout=1) as response:
            return response.status == 200 and json.loads(response.read()) == {'ready': True}
    except (URLError, ValueError, TimeoutError):
        return False


def preflight():
    result = web_preflight()
    if not ready():
        if os.geteuid() != 0:
            raise RuntimeError('The benchmark manager must prepare the offer service before candidate work')
        process = subprocess.Popen([sys.executable, '-I', str(ROOT/'offer_service.py'), '--events', str(ROOT/'events.json'), '--port', '38900'],
                                   stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        for _ in range(100):
            if ready():
                break
            if process.poll() is not None:
                raise RuntimeError('Prepared offer service exited')
            time.sleep(0.02)
        else:
            process.terminate()
            raise RuntimeError('Prepared offer service did not become healthy')
    with urlopen('http://127.0.0.1:38900/offers?after=0', timeout=2) as response:
        events=json.loads(response.read())
    assert events['events'][0]['external_id']=='offer-example'
    result.update(offer_service_ready=True,offer_service_url='http://127.0.0.1:38900')
    return result


if __name__=='__main__':
    print(json.dumps(preflight()))
