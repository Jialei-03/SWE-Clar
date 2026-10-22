"""Existing JSON transport, separate from player validation and optimization."""
import json
import sys
from pathlib import Path


def read_request(path=None):
    request = json.loads(Path(path).read_text() if path else sys.stdin.read())
    if not isinstance(request, dict) or not {'players', 'limit', 'mode'} <= request.keys():
        raise ValueError('Request requires players, limit and mode')
    return request
