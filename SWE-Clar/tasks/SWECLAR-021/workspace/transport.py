"""One bounded, idempotency-keyed HTTP delivery per explicit command."""
import json
from urllib.request import Request,urlopen
from urllib.parse import quote
from urllib.error import HTTPError,URLError


def deliver(base, envelope):
    try:
        request = Request(base.rstrip('/') + '/deliveries/' + envelope['target'],
            data=json.dumps(envelope,ensure_ascii=False,allow_nan=False).encode(),
            headers={'Content-Type':'application/json','Idempotency-Key':quote(envelope['request_id'],safe='')},method='POST')
        with urlopen(request,timeout=5) as response:
            if response.status not in [200,201]: return False
            value = json.loads(response.read(262145))
        return isinstance(value,dict) and value.get('accepted') is True and value.get('request_id') == envelope['request_id'] and value.get('target') == envelope['target']
    except (OSError,ValueError,UnicodeError,HTTPError,URLError): return False
