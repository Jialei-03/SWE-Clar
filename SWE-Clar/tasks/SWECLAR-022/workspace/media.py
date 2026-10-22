"""Decode real PNG pixels and discard all source metadata."""
import base64
from io import BytesIO
from PIL import Image


def sanitize(encoded):
    if not isinstance(encoded, str) or len(encoded) > 699052:
        raise ValueError('Invalid encoding')
    raw = base64.b64decode(encoded, validate=True)
    if not 1 <= len(raw) <= 524288:
        raise ValueError('Invalid size')
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
