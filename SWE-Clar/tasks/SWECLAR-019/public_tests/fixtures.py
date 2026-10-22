"""Independently generated image samples. No external assets are loaded."""
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw


def sample_png(color=(48, 120, 88, 255)):
    image = Image.new('RGBA', (96, 72), color)
    drawing = ImageDraw.Draw(image); drawing.rectangle((16, 16, 80, 56), outline=(240, 225, 174, 255), width=4)
    result = BytesIO(); image.save(result, format='PNG'); return result.getvalue()


def prepare_samples(directory='/tmp/sweclar-route-samples'):
    root = Path(directory); root.mkdir(parents=True, exist_ok=True)
    for name, color in [('avatar.png', (48, 120, 88, 255)), ('waypoint.png', (79, 103, 168, 255))]:
        (root / name).write_bytes(sample_png(color))
    return root
