"""Decode and regenerate actual PNG pixels without source metadata."""
import base64
from io import BytesIO
from PIL import Image


def sanitize(encoded):
    if not isinstance(encoded, str): raise ValueError('Expected PNG Base64')
    raw = base64.b64decode(encoded, validate=True)
    if not 1 <= len(raw) <= 524288: raise ValueError('Invalid PNG size')
    with Image.open(BytesIO(raw)) as source:
        if source.format != 'PNG' or not (1 <= source.width <= 1024 and 1 <= source.height <= 1024):
            raise ValueError('Invalid PNG dimensions or format')
        source.verify()
    with Image.open(BytesIO(raw)) as source:
        source.load()
        clean = Image.new('RGBA', source.size)
        clean.paste(source.convert('RGBA'))
    output = BytesIO(); clean.save(output, format='PNG')
    return output.getvalue(), clean.width, clean.height
