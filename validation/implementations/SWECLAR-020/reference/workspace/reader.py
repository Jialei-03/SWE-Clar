"""Read immutable simulator records through the disclosed HTTP protocol."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen
from store import Failure


def fetch_reading(base, key):
    try:
        with urlopen(base.rstrip('/') + '/readings/' + quote(key, safe=''), timeout=5) as response:
            if response.status != 200:
                raise ValueError('unexpected reader status')
            value = json.loads(response.read(65537))
        if not isinstance(value, dict) or not isinstance(value.get('reading'), dict):
            raise ValueError('invalid reader response')
        value = value['reading']
        if value.get('id') != key:
            raise ValueError('reader identity mismatch')
        if not all(isinstance(value.get(k), str) and 1 <= len(value[k]) <= 100 for k in ['uid', 'device_id']):
            raise ValueError('invalid reader string')
        if value.get('interaction') not in ['tap', 'proximity']:
            raise ValueError('invalid reader interaction')
        if type(value.get('at')) is not int or not 0 <= value['at'] <= 2000000000:
            raise ValueError('invalid reader time')
        return {k: value[k] for k in ['id', 'uid', 'device_id', 'interaction', 'at']}
    except HTTPError as error:
        if error.code == 404: raise Failure(404, 'not_found') from error
        raise Failure(502, 'reader_unavailable') from error
    except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError, AssertionError, UnicodeError) as error:
        raise Failure(502, 'reader_unavailable') from error
