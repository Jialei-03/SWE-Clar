"""Generic integer-lattice computation; independently authored benchmark source."""
from math import gcd

POLICIES = ('all', 'coprime', 'opposite_parity')
COORDINATES = ('raw', 'by_total', 'weighted')


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid integer range')
    return value


def coefficients(a, b):
    integer(a, 2, 39); integer(b, 1, 19)
    if a <= b or a + b > 40:
        raise ValueError('Invalid coefficients')


def pairs(total, family_policy):
    integer(total, 3, 40)
    if family_policy not in POLICIES:
        raise ValueError('Unknown family policy')
    result = []
    for b in range(1, (total + 1) // 2):
        a = total - b
        # TODO: implement the clarified selectable family policies.
        result.append((a, b))
    return result


def solve(a, b, limit):
    coefficients(a, b); integer(limit, a + b + 1, 600)
    result = {}
    for n in range(a + b + 1, limit + 1):
        points = []
        for x in range(1, (n - b) // a + 1):
            remainder = n - a * x
            if remainder % b == 0:
                points.append((x, remainder // b))
        if points:
            result[n] = points
    return result


def transform(x, y, n, a, b, coordinates):
    coefficients(a, b); integer(x, 1, 600); integer(y, 1, 600); integer(n, 1, 600)
    if a * x + b * y != n or coordinates not in COORDINATES:
        raise ValueError('Invalid solution or coordinates')
    # TODO: implement normalized views after clarification.
    return x, y


def geometry(problem):
    if not isinstance(problem, dict) or set(problem) != {'total', 'limit', 'family_policy', 'coordinates'}:
        raise ValueError('Invalid problem fields')
    total, limit = problem['total'], problem['limit']
    integer(total, 3, 40); integer(limit, total + 1, 600)
    if problem['coordinates'] not in COORDINATES:
        raise ValueError('Unknown coordinates')
    families = []
    for a, b in pairs(total, problem['family_policy']):
        raw = solve(a, b, limit)
        lines = [{'n': n, 'points': [transform(x, y, n, a, b, problem['coordinates']) for x, y in points]}
                 for n, points in raw.items()]
        families.append({'a': a, 'b': b, 'lines': lines, 'point_count': sum(len(line['points']) for line in lines)})
    return {'problem': dict(problem), 'families': families}
