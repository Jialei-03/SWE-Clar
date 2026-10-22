"""Integer-lattice computation used by both the HTTP service and development API."""
from math import gcd


POLICIES = ('all', 'coprime', 'opposite_parity')
COORDINATES = ('raw', 'by_total', 'weighted')


def integer(value, low, high):
    """Validate a JSON-style integer without accepting booleans or floats."""
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid integer range')
    return value


def coefficients(a, b):
    """Validate one coefficient family."""
    # The remaining constraints imply the useful upper bounds on both
    # coefficients, so keeping the validation in terms of the public rule
    # avoids accepting a special case that cannot be a family.
    if type(a) is not int or type(b) is not int:
        raise ValueError('Invalid coefficients')
    if a <= b or b < 1 or a + b > 40:
        raise ValueError('Invalid coefficients')


def pairs(total, family_policy):
    """Return accepted (a, b) families in increasing-b order."""
    integer(total, 3, 40)
    if type(family_policy) is not str or family_policy not in POLICIES:
        raise ValueError('Unknown family policy')

    result = []
    # b < a and a+b=total.  The range stops before the diagonal for both
    # even and odd totals.
    for b in range(1, (total + 1) // 2):
        a = total - b
        accepted = (
            family_policy == 'all'
            or (family_policy == 'coprime' and gcd(a, b) == 1)
            or (family_policy == 'opposite_parity' and
                (a % 2) != (b % 2) and gcd(a, b) == 1)
        )
        if accepted:
            result.append((a, b))
    return result


def solve(a, b, limit):
    """Enumerate positive raw solutions, retaining only nonempty levels."""
    coefficients(a, b)
    integer(limit, a + b + 1, 600)

    result = {}
    for n in range(a + b + 1, limit + 1):
        points = []
        # x is the public ordering key.  The upper bound ensures y is
        # positive, and the divisibility test handles non-coprime pairs too.
        for x in range(1, (n - b) // a + 1):
            remainder = n - a * x
            if remainder % b == 0:
                points.append((x, remainder // b))
        if points:
            result[n] = points
    return result


def transform(x, y, n, a, b, coordinates):
    """Transform one valid positive raw solution into the requested view."""
    coefficients(a, b)
    integer(x, 1, 600)
    integer(y, 1, 600)
    integer(n, 1, 600)
    if type(coordinates) is not str or coordinates not in COORDINATES:
        raise ValueError('Unknown coordinates')
    if a * x + b * y != n:
        raise ValueError('Invalid solution')

    if coordinates == 'raw':
        return x, y
    if coordinates == 'by_total':
        return x / n, y / n
    return (a * x) / n, (b * y) / n


def geometry(problem):
    """Compute the complete HTTP result shape for one validated problem."""
    if not isinstance(problem, dict) or set(problem.keys()) != {
        'total', 'limit', 'family_policy', 'coordinates'
    }:
        raise ValueError('Invalid problem fields')

    total = problem['total']
    limit = problem['limit']
    family_policy = problem['family_policy']
    coordinates = problem['coordinates']
    integer(total, 3, 40)
    integer(limit, total + 1, 600)
    if type(coordinates) is not str or coordinates not in COORDINATES:
        raise ValueError('Unknown coordinates')

    families = []
    for a, b in pairs(total, family_policy):
        raw = solve(a, b, limit)
        lines = [
            {
                'n': n,
                'points': [
                    transform(x, y, n, a, b, coordinates)
                    for x, y in points
                ],
            }
            for n, points in raw.items()
        ]
        families.append({
            'a': a,
            'b': b,
            'lines': lines,
            'point_count': sum(len(line['points']) for line in lines),
        })

    # Values have all been validated above; preserve the public problem shape
    # and do not add server-side state to it.
    return {
        'problem': {
            'total': total,
            'limit': limit,
            'family_policy': family_policy,
            'coordinates': coordinates,
        },
        'families': families,
    }
