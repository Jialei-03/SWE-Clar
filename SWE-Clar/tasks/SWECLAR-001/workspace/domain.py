"""Independent listing validation, access policy and comparable calculations."""

class AppError(Exception):
    def __init__(self, status, errors):
        super().__init__(str(errors))
        self.status, self.errors = status, errors


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def validate_fields(body, current=None):
    fields = {'label', 'property_type', 'bedrooms', 'bathrooms', 'floor_area', 'asking_price', 'features'}
    errors = {key: 'not editable' for key in body.keys() - fields}
    data = {key: value for key, value in (current or {}).items() if key in fields}
    data.update(body)
    label = data.get('label')
    if not isinstance(label, str) or not label.strip() or len(label.strip()) > 120:
        errors['label'] = 'nonempty string of at most 120 characters required'
    else:
        data['label'] = label.strip()
    if data.get('property_type') not in ['house', 'apartment']:
        errors['property_type'] = 'house or apartment required'
    for key, low, high in [('bedrooms', 0, 10), ('bathrooms', 1, 10), ('floor_area', 10, 2000), ('asking_price', 1, 10**12)]:
        if not integer(data.get(key), low, high):
            errors[key] = f'integer in {low}..{high} required'
    features = data.get('features', [])
    if not isinstance(features, list) or len(features) > 20 or any(not isinstance(x, str) or not x.strip() or len(x.strip()) > 80 for x in features):
        errors['features'] = 'at most 20 nonempty strings, each at most 80 characters'
    else:
        data['features'] = list(dict.fromkeys(x.strip() for x in features))
    if errors:
        raise AppError(400, errors)
    return data


def may_read(actor, listing):
    # Workspace scoping is awaiting the client policy.
    return True


def may_write(actor, listing):
    return True


def price(listing, comparables):
    # Comparable eligibility and arithmetic are awaiting clarification.
    return None


def describe(listing, count, tone):
    facts = f"{listing['label']}: {listing['property_type']}, {listing['bedrooms']} bedrooms, {listing['bathrooms']} bathrooms, {listing['floor_area']} square units, asking {listing['asking_price']}."
    features = ' Listed features: ' + ', '.join(listing['features']) + '.' if listing['features'] else ''
    variants = [f"{tone} overview. {facts}{features}", f"{tone} property summary: {facts}{features}", f"{tone} listing details. {facts}{features}"]
    return variants[:count]


def analysis(listing, body):
    if type(body.get('count')) is not int or body['count'] not in [2, 3] or body.get('tone') not in ['warm', 'concise'] or not isinstance(body.get('comparables'), list) or len(body['comparables']) > 1000:
        raise AppError(400, {'analysis': 'count 2|3, tone warm|concise and at most 1000 comparables required'})
    return {'pricing': price(listing, body['comparables']), 'descriptions': describe(listing, body['count'], body['tone'])}
