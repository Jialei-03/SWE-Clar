"""Incremental itinerary processing."""


def iter_json_objects(chunks):
    """Yield each complete JSON object found in text chunks."""
    raise NotImplementedError


def stream_itinerary(chunks, location, find_place, find_replacement):
    """Yield one SSE data record per acceptable resolved activity."""
    raise NotImplementedError

