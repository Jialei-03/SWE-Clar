"""Decode real PNG pixels and discard all source metadata."""
import base64
import struct
from io import BytesIO
from PIL import Image


def _require_complete_png(raw):
    """Reject a valid PNG followed by unrelated trailing bytes."""
    if raw[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Expected PNG')
    position = 8
    found_iend = False
    while position < len(raw):
        if position + 12 > len(raw):
            raise ValueError('Truncated PNG')
        length = struct.unpack('>I', raw[position:position + 4])[0]
        end = position + 12 + length
        if end > len(raw):
            raise ValueError('Truncated PNG')
        chunk_type = raw[position + 4:position + 8]
        if chunk_type == b'IEND':
            if length != 0 or end != len(raw):
                raise ValueError('Trailing PNG data')
            found_iend = True
            break
        position = end
    if not found_iend:
        raise ValueError('Missing PNG end')


def sanitize(encoded):
    if not isinstance(encoded, str) or len(encoded) > 699052:
        raise ValueError('Invalid encoding')
    raw = base64.b64decode(encoded, validate=True)
    if not 1 <= len(raw) <= 524288:
        raise ValueError('Invalid size')
    _require_complete_png(raw)
    with Image.open(BytesIO(raw)) as source:
        if source.format != 'PNG' or getattr(source, 'is_animated', False):
            raise ValueError('Expected nonanimated PNG')
        if not (1 <= source.width <= 1024 and 1 <= source.height <= 1024):
            raise ValueError('Invalid dimensions')
        source.verify()
    with Image.open(BytesIO(raw)) as source:
        source.load()
        clean = Image.new('RGBA', source.size)
        clean.paste(source.convert('RGBA'))
    output = BytesIO()
    clean.save(output, format='PNG')
    return output.getvalue(), clean.width, clean.height
