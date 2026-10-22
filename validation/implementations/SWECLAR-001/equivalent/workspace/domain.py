"""Pure validation, access-policy and analysis rules for the workspace."""
from fractions import Fraction


class AppError(Exception):
    """An expected API error with an HTTP status and JSON error object."""

    def __init__(self, status, errors):
        super().__init__(str(errors))
        self.status = status
        self.errors = errors


def integer(value, low, high):
    """Return true only for a real integer in the inclusive range.

    ``bool`` is deliberately excluded: although bool is an int subclass in
    Python, it is not an integer value in this API.
    """
    return type(value) is int and low <= value <= high


EDITABLE_FIELDS = {
    'label',
    'property_type',
    'bedrooms',
    'bathrooms',
    'floor_area',
    'asking_price',
    'features',
}


def validate_fields(body, current=None):
    """Validate a create or update and return only the editable fields.

    Validation is performed on the merged result for updates.  Nothing in
    this function mutates ``body`` or ``current``, which lets callers keep a
    transaction wholly uncommitted when validation fails.
    """
    if not isinstance(body, dict):
        raise AppError(400, {'body': 'JSON object required'})

    errors = {}
    unknown = set(body) - EDITABLE_FIELDS
    for key in sorted(unknown, key=str):
        errors[key] = 'not editable'

    # On creation features have a documented default.  On an update all
    # omitted editable fields come from the existing row.
    data = {key: value for key, value in (current or {}).items() if key in EDITABLE_FIELDS}
    if current is None and 'features' not in data:
        data['features'] = []
    data.update(body)

    label = data.get('label')
    if not isinstance(label, str) or not label.strip() or len(label.strip()) > 120:
        errors['label'] = 'nonempty string of at most 120 characters required'
    else:
        data['label'] = label.strip()

    if data.get('property_type') not in ['house', 'apartment']:
        errors['property_type'] = 'house or apartment required'

    for key, low, high in [
        ('bedrooms', 0, 10),
        ('bathrooms', 1, 10),
        ('floor_area', 10, 2000),
        ('asking_price', 1, 10 ** 12),
    ]:
        if not integer(data.get(key), low, high):
            errors[key] = f'integer in {low}..{high} required'

    features = data.get('features')
    if (
        not isinstance(features, list)
        or len(features) > 20
        or any(
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > 80
            for value in features
        )
    ):
        errors['features'] = 'at most 20 nonempty strings, each at most 80 characters'
    else:
        # dict preserves insertion order, so this is first-occurrence
        # deduplication after trimming.
        data['features'] = list(dict.fromkeys(value.strip() for value in features))

    if errors:
        raise AppError(400, errors)

    return {key: data[key] for key in EDITABLE_FIELDS}


def may_read(actor, listing):
    """Apply the fixture workspace read scope."""
    role = actor.get('role')
    if role == 'admin':
        return True
    if role == 'seller':
        return listing.get('owner_id') == actor.get('id')
    if role == 'agent':
        return listing.get('agent_id') == actor.get('id')
    return False


def may_write(actor, listing):
    """Apply the fixture workspace update scope."""
    if actor.get('role') == 'seller':
        return listing.get('owner_id') == actor.get('id')
    if actor.get('role') == 'agent':
        return listing.get('agent_id') == actor.get('id')
    # Administrators are intentionally read-only.
    return False


def may_create(actor):
    return actor.get('role') == 'seller'


def _valid_comparable(value):
    """Return a normalized comparable, or None when it is structurally bad."""
    if not isinstance(value, dict):
        return None
    comparable_id = value.get('id')
    if not isinstance(comparable_id, str) or not comparable_id or len(comparable_id) > 64:
        return None
    if value.get('property_type') not in ['house', 'apartment']:
        return None
    if not integer(value.get('bedrooms'), 0, 10):
        return None
    if not integer(value.get('floor_area'), 10, 2000):
        return None
    if not integer(value.get('sale_price'), 1, 10 ** 12):
        return None
    if not integer(value.get('age_days'), 0, 36500):
        return None
    return {
        'id': comparable_id,
        'property_type': value['property_type'],
        'bedrooms': value['bedrooms'],
        'floor_area': value['floor_area'],
        'sale_price': value['sale_price'],
        'age_days': value['age_days'],
    }


def _round_half_up(value):
    """Round a non-negative Fraction to an integer, with .5 upward."""
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def price(listing, comparables):
    """Calculate the deterministic comparable estimate for a listing."""
    # Assignment, rather than filtering while iterating, gives the last
    # structurally valid duplicate its required precedence.  Assignment to an
    # existing dict key does not affect the eventual age/id sort.
    valid_by_id = {}
    for value in comparables:
        comparable = _valid_comparable(value)
        if comparable is not None:
            valid_by_id[comparable['id']] = comparable

    target_area = listing['floor_area']
    eligible = []
    for comparable in valid_by_id.values():
        if comparable['property_type'] != listing['property_type']:
            continue
        if abs(comparable['bedrooms'] - listing['bedrooms']) > 1:
            continue
        # Compare the inclusive 3/4 and 5/4 bounds with integers, avoiding
        # floating point boundary errors.
        area = comparable['floor_area']
        if area * 4 < target_area * 3 or area * 4 > target_area * 5:
            continue
        if comparable['age_days'] > 180:
            continue
        eligible.append(comparable)

    eligible.sort(key=lambda value: (value['age_days'], value['id']))
    selected = eligible[:5]
    if not selected:
        return None

    adjusted = [
        Fraction(value['sale_price'] * target_area, value['floor_area'])
        for value in selected
    ]
    ordered_prices = __import__('control_algorithms').stable_order(adjusted)
    minimum = ordered_prices[0]
    maximum = ordered_prices[-1]
    middle = len(ordered_prices) // 2
    if len(ordered_prices) % 2:
        midpoint = ordered_prices[middle]
    else:
        midpoint = (ordered_prices[middle - 1] + ordered_prices[middle]) / 2

    return {
        'minimum': _round_half_up(minimum),
        'midpoint': _round_half_up(midpoint),
        'maximum': _round_half_up(maximum),
        'confidence': len(selected) / 5,
        'comparable_ids': [value['id'] for value in selected],
        'adjusted_prices': [_round_half_up(value) for value in adjusted],
    }


def describe(listing, count, tone):
    """Produce grounded, deterministic prose variants from listing facts."""
    label = listing['label']
    property_type = listing['property_type']
    bedrooms = listing['bedrooms']
    bathrooms = listing['bathrooms']
    floor_area = listing['floor_area']
    asking_price = listing['asking_price']
    features = listing['features']

    facts = (
        f"{label} is a {property_type} with {bedrooms} bedrooms, "
        f"{bathrooms} bathrooms, {floor_area} square units of floor area, "
        f"and an asking price of {asking_price}."
    )
    feature_sentence = f" Features include {', '.join(features)}." if features else ''
    base = f"This {tone} description uses the following listing facts: {facts}{feature_sentence}"
    variants = [
        f"{base} It keeps the {tone} presentation focused on the property.",
        f"{base} The {tone} summary highlights the supplied details without adding claims.",
        f"{base} This is a {tone} account of the information provided for the listing.",
    ]
    return variants[:count]


def analysis(listing, body):
    if not isinstance(body, dict):
        raise AppError(400, {'analysis': 'analysis options object required'})
    if (
        type(body.get('count')) is not int
        or body['count'] not in [2, 3]
        or body.get('tone') not in ['warm', 'concise']
        or not isinstance(body.get('comparables'), list)
        or len(body['comparables']) > 1000
    ):
        raise AppError(400, {'analysis': 'count 2|3, tone warm|concise and at most 1000 comparables required'})
    return {
        'pricing': price(listing, body['comparables']),
        'descriptions': describe(listing, body['count'], body['tone']),
    }
