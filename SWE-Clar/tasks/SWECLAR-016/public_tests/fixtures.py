"""Generate synthetic PNG fixtures with the prepared font; no source assets."""
from io import BytesIO
import subprocess
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


def screenshot(lines, width=1100):
    image = Image.new('RGB', (width, max(220, 86 * len(lines) + 40)), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 36)
    for index, line in enumerate(lines):
        draw.text((24, 24 + 86 * index), line, font=font, fill='black')
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('SyntheticMarker', 'REMOVE_SYNTHETIC_MARKER')
    output = BytesIO()
    image.save(output, format='PNG', pnginfo=metadata)
    raw = output.getvalue()
    # An ambiguous fixture is an environment/material failure, not an agent defect.
    result = subprocess.run(['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', '6'],
                            input=raw, capture_output=True, timeout=20, check=True)
    actual = [line.strip() for line in result.stdout.decode().splitlines() if line.strip()]
    if actual != lines:
        raise RuntimeError('Synthetic OCR fixture was not recognized as intended: ' + repr(actual))
    return raw


def photo(color='white', size=(64, 48)):
    image = Image.new('RGB', size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, min(size[0] - 1, 32), min(size[1] - 1, 24)), outline='#738b83', width=2)
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()
