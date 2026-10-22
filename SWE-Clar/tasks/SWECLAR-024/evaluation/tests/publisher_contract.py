"""Invalidate a publisher credential without assuming a literal stream-key URL."""
from urllib.parse import quote, urlsplit, urlunsplit

def invalid_publisher_url(url: str, configured_key: str) -> str:
    parts=urlsplit(url)
    if parts.scheme!='rtmp' or not parts.hostname:
        raise AssertionError('Expected a usable RTMP publisher URL')
    # Credential position is opaque. Remove the entire capability-bearing suffix
    # while keeping the actual listening endpoint, including IPv6 brackets/port.
    # Arbitrary unauthenticated publish paths must be rejected by RU-003.
    authority=parts.netloc.rsplit('@',1)[-1]
    return urlunsplit(parts._replace(netloc=authority,path='/unauthenticated-publisher/probe',query='',fragment=''))
