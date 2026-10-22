"""Deterministic operations on independently generated grayscale calibration frames."""
import math
import re


def parse_pgm(text):
    if not isinstance(text, str) or len(text) > 150000:
        raise ValueError('Expected a bounded P2 PGM string')
    words = re.sub(r'#[^\n]*', '', text).split()
    if len(words) < 4 or words[0] != 'P2':
        raise ValueError('Expected P2 width height 255 followed by pixels')
    if any(not re.fullmatch(r'[0-9]+', x) for x in words[1:]):
        raise ValueError('PGM samples must be unsigned integers')
    width, height, maximum = map(int, words[1:4])
    if not (1 <= width <= 128 and 1 <= height <= 128 and maximum == 255):
        raise ValueError('PGM dimensions must be 1..128 and maximum 255')
    pixels = list(map(int, words[4:]))
    if len(pixels) != width * height or any(p > 255 for p in pixels):
        raise ValueError('Incorrect PGM sample count or value')
    return {'width': width, 'height': height, 'pixels': pixels}


def measure(image, config):
    # Provisional whole-mask measurement; complete the agreed target-selection policy.
    width = image['width']
    dark = [i for i, value in enumerate(image['pixels']) if value < 64]
    if not dark:
        return None
    return {'area': len(dark), 'cx': sum(i % width for i in dark) / len(dark),
            'cy': sum(i // width for i in dark) / len(dark)}
