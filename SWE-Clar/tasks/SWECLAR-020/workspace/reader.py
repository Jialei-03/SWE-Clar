"""Read immutable simulator records through the disclosed HTTP protocol."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen
from store import Failure


def fetch_reading(base, key):
    try:
        with urlopen(base.rstrip('/') + '/readings/' + quote(key, safe=''), timeout=5) as response:
            value = json.loads(response.read(65537))['reading']
        assert isinstance(value, dict) and value['id'] == key
        assert all(isinstance(value[k], str) and 1 <= len(value[k]) <= 100 for k in ['uid', 'device_id'])
        assert value['interaction'] in ['tap', 'proximity']
        assert type(value['at']) is int and 0 <= value['at'] <= 2000000000
        return {k: value[k] for k in ['id', 'uid', 'device_id', 'interaction', 'at']}
    except HTTPError as error:
        if error.code == 404: raise Failure(404, 'not_found') from error
        raise Failure(502, 'reader_unavailable') from error
    except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError, AssertionError) as error:
        raise Failure(502, 'reader_unavailable') from error
