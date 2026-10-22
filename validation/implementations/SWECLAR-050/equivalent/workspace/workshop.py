"""Validation and atomic application of workshop commands."""
import copy
import math
import re

from battle import begin, distance, step


class Rejected(ValueError):
    """A client command that must be returned as HTTP 400."""


def require(condition, code='invalid_command'):
    if not condition:
        raise Rejected(code)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,40}', value))
    return value


def number(value, low, high):
    # bool is an int subclass, so use an exact type check.  This also rejects
    # strings and JSON null rather than silently coercing them.  Very large
    # JSON integers can raise OverflowError during float finiteness testing;
    # they are invalid just like infinity and must still become a normal
    # client rejection.
    require(type(value) in (int, float))
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    require(finite and low <= value <= high)
    return value


def template(value):
    """Validate and normalise a complete template record."""
    require(isinstance(value, dict))
    result = {'id': identifier(value.get('id'))}

    name = value.get('name')
    require(isinstance(name, str) and 1 <= len(name.strip()) <= 60)
    result['name'] = name.strip()

    kind = value.get('kind')
    require(kind in ('melee', 'ranged'))
    result['kind'] = kind

    for key, low, high in [
        ('health', 1, 1000),
        ('attack', 1, 100),
        ('defense', 0, 100),
        ('speed', 0.1, 5),
        ('range', 0.8, 8),
        ('projectile_speed', 0.1, 20),
    ]:
        result[key] = number(value.get(key), low, high)

    cooldown = value.get('cooldown')
    require(type(cooldown) is int and 1 <= cooldown <= 100)
    result['cooldown'] = cooldown
    return result


def initial():
    """Return a fresh default store value (never a shared mutable object)."""
    return {
        'config': {
            'templates': [
                {
                    'id': 'GUARD', 'name': 'Guard', 'kind': 'melee',
                    'health': 40, 'attack': 8, 'defense': 2, 'speed': 2,
                    'range': 0.9, 'cooldown': 5, 'projectile_speed': 8,
                },
                {
                    'id': 'SCOUT', 'name': 'Scout', 'kind': 'ranged',
                    'health': 28, 'attack': 6, 'defense': 1, 'speed': 2.5,
                    'range': 3, 'cooldown': 8, 'projectile_speed': 7,
                },
            ],
            'placements': [
                {'id': 'A1', 'template_id': 'GUARD', 'team': 'A', 'x': -4, 'z': -2},
                {'id': 'A2', 'template_id': 'SCOUT', 'team': 'A', 'x': -4, 'z': 2},
                {'id': 'B1', 'template_id': 'GUARD', 'team': 'B', 'x': 4, 'z': -2},
                {'id': 'B2', 'template_id': 'SCOUT', 'team': 'B', 'x': 4, 'z': 2},
            ],
            'max_ticks': 300,
        },
        'battle': None,
    }


def _template_index(config, template_id):
    """Return a catalog position without changing catalog order."""
    for index, value in enumerate(config['templates']):
        if value['id'] == template_id:
            return index
    return None


def _template_exists(config, template_id):
    return _template_index(config, template_id) is not None


def _placement_index(config, placement_id):
    for index, placement in enumerate(config['placements']):
        if placement['id'] == placement_id:
            return index
    return None


def apply(data, command):
    """Apply one command to a deep copy, or raise without changing ``data``.

    The server wraps the returned value in one SQLite transaction.  Keeping
    all validation and mutation on this copy gives the same whole-command
    atomicity to direct callers as it does to HTTP callers.
    """
    require(isinstance(command, dict))
    result = copy.deepcopy(data)
    config = result['config']
    kind = command.get('type')

    # Reset is the one editing-adjacent operation allowed while a completed
    # battle is retained.  It never changes the saved setup.
    if kind == 'reset':
        result['battle'] = None
        return result

    if kind == 'start':
        require(result['battle'] is None, 'reset_required')
        require(
            any(placement['team'] == 'A' for placement in config['placements'])
            and any(placement['team'] == 'B' for placement in config['placements']),
            'both_teams_required',
        )
        result['battle'] = begin(config)
        return result

    if kind == 'step':
        require(result['battle'] is not None and result['battle']['status'] == 'running', 'not_running')
        ticks = command.get('ticks', 1)
        require(type(ticks) is int and 1 <= ticks <= 50)
        result['battle'] = step(result['battle'], ticks)
        return result

    # Every remaining command edits the setup and is locked by both running
    # and finished battle snapshots.
    require(result['battle'] is None, 'editing_locked')

    if kind == 'template':
        value = template(command.get('value'))
        existing = _template_index(config, value['id'])
        if existing is None:
            require(len(config['templates']) < 32, 'catalog_full')
            config['templates'].append(value)
        else:
            # Replacement by position preserves the catalog's public order.
            config['templates'][existing] = value

    elif kind == 'delete_template':
        template_id = command.get('id')
        require(_template_exists(config, template_id), 'missing_template')
        require(
            not any(placement['template_id'] == template_id for placement in config['placements']),
            'template_in_use',
        )
        config['templates'] = [
            item for item in config['templates'] if item['id'] != template_id
        ]

    elif kind == 'place':
        placement_id = identifier(command.get('id'))
        template_id = command.get('template_id')
        require(_template_exists(config, template_id), 'missing_template')
        require(command.get('team') in ('A', 'B'))
        x = number(command.get('x'), -7.6, 7.6)
        z = number(command.get('z'), -5.6, 5.6)
        placement = {
            'id': placement_id,
            'template_id': template_id,
            'team': command['team'],
            'x': x,
            'z': z,
        }

        existing = _placement_index(config, placement_id)
        others = [
            item for index, item in enumerate(config['placements'])
            if index != existing
        ]
        # Editor legality is an explicit schema boundary: centres must be at
        # least one unit diameter apart.  The simulation separately allows a
        # tiny tolerance for its continuous movement comparisons.
        require(all(distance(placement, other) >= 0.8 for other in others), 'occupied')
        if existing is None:
            require(len(config['placements']) < 32, 'arena_full')
            config['placements'].append(placement)
        else:
            # Updating an instance preserves the ordered placement list.
            config['placements'][existing] = placement

    elif kind == 'remove':
        placement_id = command.get('id')
        existing = _placement_index(config, placement_id)
        require(existing is not None, 'missing_unit')
        del config['placements'][existing]

    elif kind == 'clear':
        # Clear is intentionally narrower than reset: templates and limit
        # remain, while only the editable placements disappear.
        config['placements'] = []

    elif kind == 'limit':
        value = command.get('value')
        require(type(value) is int and 1 <= value <= 1000)
        config['max_ticks'] = value

    else:
        raise Rejected('invalid_command')

    return result
