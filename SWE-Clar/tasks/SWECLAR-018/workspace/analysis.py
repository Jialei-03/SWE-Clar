"""Capture replay: validate inputs, derive pixel measurements, then evaluate quality."""
import math
from vision import parse_pgm, measure

INTEGER_FIELDS = {'phase_ms': (100, 10000), 'threshold': (0, 255),
                  'min_area': (1, 16384), 'max_area': (1, 16384), 'max_gap_ms': (1, 20000)}
FLOAT_FIELDS = {'max_motion_px': (0, 256), 'max_lighting_delta': (0, 255),
                'max_area_change': (0, 100), 'max_gaze_px': (0, 256)}


def number(value, low, high, integer=False):
    return (type(value) in ((int,) if integer else (int, float))
            and math.isfinite(value) and low <= value <= high)


def validate(document):
    if not isinstance(document, dict):
        raise ValueError('Expected a capture object')
    caps, config, frames = (document.get(k) for k in ('capabilities', 'config', 'frames'))
    if not isinstance(caps, dict) or not isinstance(config, dict) or not isinstance(frames, list):
        raise ValueError('Missing capabilities, config or frames')
    for key, bounds in {'fps': (1, 240), 'width': (1, 128), 'height': (1, 128)}.items():
        if not number(caps.get(key), *bounds, integer=True):
            raise ValueError('Invalid capability: ' + key)
    for key, bounds in INTEGER_FIELDS.items():
        if not number(config.get(key), *bounds, integer=True):
            raise ValueError('Invalid integer config: ' + key)
    for key, bounds in FLOAT_FIELDS.items():
        if not number(config.get(key), *bounds):
            raise ValueError('Invalid numeric config: ' + key)
    if config['min_area'] > config['max_area'] or not 1 <= len(frames) <= 100:
        raise ValueError('Invalid area bounds or frame count')
    last = -1
    for frame in frames:
        if not isinstance(frame, dict) or not number(frame.get('t_ms'), 0, 2 * config['phase_ms'] - 1, True):
            raise ValueError('Invalid frame time')
        target = frame.get('target')
        if (frame['t_ms'] <= last or not isinstance(frame.get('pgm'), str)
                or not isinstance(target, list) or len(target) != 2
                or not number(target[0], 0, caps['width'] - 1)
                or not number(target[1], 0, caps['height'] - 1)):
            raise ValueError('Frames need increasing times, PGM and an in-image target [x,y]')
        last = frame['t_ms']
    return caps, config, frames


def classify(rows, images, config):
    # Current preview-oriented result; implement the agreed quality/decision rules.
    return 'stable', 'within_limits'


def analyze(document):
    caps, config, frames = validate(document)
    if caps['fps'] < 10 or caps['width'] < 16 or caps['height'] < 16:
        return {'verdict': 'not_measurable', 'reason': 'capability', 'measurements': []}
    images = [parse_pgm(frame['pgm']) for frame in frames]
    if any((image['width'], image['height']) != (caps['width'], caps['height']) for image in images):
        raise ValueError('Frame dimensions do not match capabilities')
    rows = []
    for frame, image in zip(frames, images):
        target = measure(image, config)
        row = {'t_ms': frame['t_ms'], 'phase': 'light',
               'area': None, 'cx': None, 'cy': None, 'gaze_error': None}
        if target:
            row.update(target)
            row['gaze_error'] = math.hypot(target['cx'] - frame['target'][0], target['cy'] - frame['target'][1])
        rows.append(row)
    verdict, reason = classify(rows, images, config)
    return {'verdict': verdict, 'reason': reason, 'measurements': rows}
