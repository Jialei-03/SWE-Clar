"""Curve geometry in a bounded, synthetic device coordinate system."""
import math


def valid_number(value):
    return type(value) in (int, float) and 0 <= value <= 100 and math.isfinite(value)


def validate_points(points):
    if not isinstance(points, list) or not 2 <= len(points) <= 32:
        raise ValueError('A curve requires 2..32 points')
    last = -1
    for point in points:
        if not isinstance(point, dict) or not all(valid_number(point.get(k)) for k in ('x', 'y')):
            raise ValueError('Coordinates must be finite numbers in 0..100')
        if point['x'] <= last:
            raise ValueError('Point x coordinates must strictly increase')
        last = point['x']
    return [{'x': p['x'], 'y': p['y']} for p in points]


def angle(points):
    a, b = points[-2:]
    return math.degrees(math.atan2(b['y'] - a['y'], b['x'] - a['x']))


def move(points, command):
    index = command.get('index')
    if type(index) is not int or not 0 <= index < len(points) or type(command.get('shift')) is not bool:
        raise ValueError('Invalid point index or shift flag')
    x, y = command.get('x'), command.get('y')
    if not valid_number(x) or not valid_number(y):
        raise ValueError('Coordinates must be finite numbers in 0..100')
    result = [p.copy() for p in points]
    # Shift currently falls back to ordinary dragging; implement the agreed geometry.
    result[index] = {'x': x, 'y': y}
    return validate_points(result)
