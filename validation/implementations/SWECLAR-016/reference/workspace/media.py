"""Validate, sanitize and recognize actual synthetic PNG assets."""
import base64
from io import BytesIO
from pathlib import Path
import re
import subprocess
from PIL import Image

MAX_UPLOAD = 524288
MAX_PIXELS = 2000000


def decoded_png(data, upload=False):
    if not isinstance(data, bytes) or not data or (upload and len(data) > MAX_UPLOAD):
        raise ValueError('Invalid PNG bytes')
    with Image.open(BytesIO(data)) as image:
        if image.format != 'PNG' or not (1 <= image.width <= 1600 and 1 <= image.height <= 1600) or image.width * image.height > MAX_PIXELS:
            raise ValueError('Invalid PNG dimensions')
        image.verify()
    with Image.open(BytesIO(data)) as image:
        image.load()
        clean = Image.new('RGB', image.size)
        clean.paste(image.convert('RGB'))
    return clean


def sanitize(encoded):
    if not isinstance(encoded, str):
        raise ValueError('Expected Base64 string')
    image = decoded_png(base64.b64decode(encoded, validate=True), upload=True)
    output = BytesIO();image.save(output, format='PNG')
    return output.getvalue(), image.width, image.height


def read_asset(root, filename):
    root = Path(root).resolve();path = root / filename
    if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError('Invalid asset file')
    data = path.read_bytes();decoded_png(data)
    return data


def extract(root, filename):
    data = read_asset(root, filename)
    result = subprocess.run(['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', '6'],
                            input=data, capture_output=True, timeout=20)
    if result.returncode:
        raise ValueError('OCR failed')
    lines = []
    for text in result.stdout.decode('utf-8').splitlines():
        text = text.strip()
        if not text:
            continue
        match = re.fullmatch(r'(me|peer)\s*:\s*(.+)', text, flags=re.IGNORECASE)
        if not match:
            raise ValueError('Unrecognized screenshot line')
        content = ' '.join(match.group(2).split())
        if not content:
            raise ValueError('Empty message')
        lines.append({'sender': match.group(1).lower(), 'text': content})
    if not lines:
        raise ValueError('Empty screenshot')
    return lines
