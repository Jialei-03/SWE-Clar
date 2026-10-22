"""Curve geometry in a bounded, synthetic device coordinate system."""
import math


_MIN_COORDINATE = 0.0
_MAX_COORDINATE = 100.0


def valid_number(value):
    """Return whether *value* is a finite JSON number in the device range.

    ``bool`` is deliberately excluded even though it is an ``int`` subclass in
    Python.  Very large JSON integers are also treated as invalid rather than
    allowing ``math.isfinite`` to raise while converting them to a float.
    """
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and _MIN_COORDINATE <= value <= _MAX_COORDINATE
    except (OverflowError, ValueError):
        return False


def validate_points(points):
    """Validate and canonicalize a curve without changing its order."""
    if not isinstance(points, list) or not 2 <= len(points) <= 32:
        raise ValueError('A curve requires 2..32 points')

    result = []
    previous_x = None
    for point in points:
        if not isinstance(point, dict) or not all(valid_number(point.get(name)) for name in ('x', 'y')):
            raise ValueError('Coordinates must be finite numbers in 0..100')
        x = point['x']
        if previous_x is not None and x <= previous_x:
            raise ValueError('Point x coordinates must strictly increase')
        result.append({'x': x, 'y': point['y']})
        previous_x = x
    return result


def angle(points):
    """Return the terminal segment angle in degrees, with Y increasing up."""
    previous, terminal = points[-2:]
    return math.degrees(math.atan2(terminal['y'] - previous['y'],
                                   terminal['x'] - previous['x']))


def move(points, command):
    """Apply one ordinary or Shift point move atomically.

    Shift rotates only the final segment.  The requested coordinates describe
    a direction from the preceding point; they are not themselves used as the
    new endpoint.
    """
    if not isinstance(command, dict):
        raise ValueError('Invalid point index or shift flag')

    index = command.get('index')
    shift = command.get('shift')
    if type(index) is not int or not 0 <= index < len(points) or type(shift) is not bool:
        raise ValueError('Invalid point index or shift flag')

    x, y = command.get('x'), command.get('y')
    if not valid_number(x) or not valid_number(y):
        raise ValueError('Coordinates must be finite numbers in 0..100')

    result = [point.copy() for point in points]
    if shift:
        if index != len(points) - 1:
            raise ValueError('Shift can only be used on the final point')

        pivot = points[-2]
        original = points[-1]
        direction_x = x - pivot['x']
        direction_y = y - pivot['y']
        direction_length = math.hypot(direction_x, direction_y)
        if direction_length == 0:
            raise ValueError('Shift direction must not point at the pivot')

        segment_length = math.hypot(original['x'] - pivot['x'],
                                    original['y'] - pivot['y'])
        projected_x = pivot['x'] + segment_length * direction_x / direction_length
        projected_y = pivot['y'] + segment_length * direction_y / direction_length

        # Check the projection itself rather than clamping it.  The complete
        # validation below also protects the ordering contract.
        if (not valid_number(projected_x) or not valid_number(projected_y)
                or projected_x <= pivot['x']):
            raise ValueError('Shift projection is outside the curve bounds')
        result[index] = {'x': projected_x, 'y': projected_y}
    else:
        result[index] = {'x': x, 'y': y}

    return validate_points(result)
