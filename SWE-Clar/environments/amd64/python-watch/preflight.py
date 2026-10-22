"""Prepare real synthetic page and receipt capabilities before candidate work."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path('/opt/sweclar')
sys.path.insert(0, str(ROOT))
from web_preflight import preflight as web_preflight


def ready():
    try:
        with urlopen('http://127.0.0.1:38920/health', timeout=1) as response:
            return response.status == 200 and json.loads(response.read()) == {'ready': True, 'service': 'synthetic-watch'}
    except (URLError, ValueError, TimeoutError):
        return False


def preflight():
    result = web_preflight()
    if not ready():
        if os.geteuid() != 0:
            raise RuntimeError('Benchmark manager must prepare the provider before candidate work')
        process = subprocess.Popen([sys.executable, '-I', str(ROOT/'watch_service.py'), '--fixtures', str(ROOT/'fixtures.json'), '--port', '38920', '--demo'],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(100):
            if ready():
                break
            if process.poll() is not None:
                raise RuntimeError('Prepared synthetic provider exited')
            time.sleep(0.02)
        else:
            process.terminate()
            process.wait(timeout=5)
            raise RuntimeError('Synthetic provider did not become healthy')
    with urlopen('http://127.0.0.1:38920/pages/demo-page-a', timeout=2) as response:
        assert response.status == 200 and b'Sample catalog' in response.read()
    with urlopen('http://127.0.0.1:38920/v1/receipts/demo-full-a', timeout=2) as response:
        receipt = json.loads(response.read())
        assert receipt == {'id':'demo-full-a','account_id':'account-a','sequence':1,'plan':'full','status':'active'}
    result.update(watch_service_ready=True, watch_service_url='http://127.0.0.1:38920', capabilities=['static-html-http', 'canonical-subscription-receipts', 'isolated-public-demo-controls'])
    return result


if __name__ == '__main__':
    print(json.dumps(preflight()))
