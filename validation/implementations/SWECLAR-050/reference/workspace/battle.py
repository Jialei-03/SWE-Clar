"""Deterministic fixed-tick combat, separate from editing and rendering.

The simulation deliberately has no wall-clock state and no random inputs.  A
battle is a JSON-serialisable value, so the server can store it and resume it
without keeping Python objects alive between requests.
"""
import copy
import math


DT = 0.1
RADIUS = 0.4
_EPSILON = 1e-9


def distance(a, b):
    """Return planar centre distance between two unit/projectile-like values."""
    return math.hypot(a['x'] - b['x'], a['z'] - b['z'])


def begin(config):
    """Create an independent battle snapshot from the editable configuration."""
    templates = {template['id']: template for template in config['templates']}
    units = []
    # Instance IDs define the simulation order, not the order in which an
    # editor happened to create the placements.
    for placement in sorted(config['placements'], key=lambda value: value['id']):
        unit = copy.deepcopy(templates[placement['template_id']])
        unit.update(copy.deepcopy(placement))
        unit.update(hp=unit['health'], next_attack=1, damage_dealt=0)
        units.append(unit)
    return {
        'status': 'running',
        'tick': 0,
        'winner': None,
        'reason': None,
        'units': units,
        'projectiles': [],
        'events': [],
        'max_ticks': config['max_ticks'],
        'next_projectile': 1,
    }


def damage(state, attacker, target, amount, kind):
    """Record a hit whose ``amount`` has already been mitigated.

    This keeps the starter module's small helper useful to callers while the
    simulation-specific wrapper below supplies the target-defense rule.
    """
    actual = min(target['hp'], max(1, amount))
    target['hp'] = max(0, target['hp'] - actual)
    attacker['damage_dealt'] += actual
    state['events'].append({
        'tick': state['tick'],
        'type': 'hit',
        'kind': kind,
        'attacker': attacker['id'],
        'target': target['id'],
        'damage': actual,
        'remaining_hp': target['hp'],
    })


def _apply_damage(state, attacker, target, amount, kind):
    """Apply one hit and record the actual (post-mitigation) loss."""
    # A hit always does at least one point, but never more than the target's
    # current health.  Keeping the subtraction here (rather than in callers)
    # makes melee and projectile hits exactly equivalent.
    damage(state, attacker, target, max(1, amount - target['defense']), kind)


def _living_target(state, unit):
    """Select the nearest living enemy, with the specified rounded tie rule."""
    candidates = [
        other for other in state['units']
        if other['hp'] > 0 and other['team'] != unit['team']
    ]
    if not candidates:
        return None
    # Only the comparison key is rounded.  The unrounded distance is used for
    # range and movement below.
    return min(candidates, key=lambda other: (round(distance(unit, other), 9), other['id']))


def _blocked(state, unit, x, z):
    """Whether a proposed centre would overlap another living unit."""
    for other in state['units']:
        if other is unit or other['hp'] <= 0:
            continue
        proposed = {'x': x, 'z': z}
        # Positions exactly one diameter apart are legal.  The epsilon avoids
        # turning harmless floating point error into a collision.
        if distance(proposed, other) < (RADIUS * 2) - _EPSILON:
            return True
    return False


def _launch(state, unit, target):
    projectile_id = state['next_projectile']
    state['next_projectile'] += 1
    state['projectiles'].append({
        'id': projectile_id,
        'attacker': unit['id'],
        'target': target['id'],
        'team': unit['team'],
        'x': unit['x'],
        'z': unit['z'],
        'speed': unit['projectile_speed'],
        'attack': unit['attack'],
    })
    state['events'].append({
        'tick': state['tick'],
        'type': 'launch',
        'kind': 'ranged',
        'attacker': unit['id'],
        'target': target['id'],
        'projectile': projectile_id,
    })


def _advance_projectiles(state):
    """Advance only projectiles that existed before this tick.

    The list is traversed in creation order.  A projectile that hits or finds
    a dead target is removed; a newly launched projectile cannot enter this
    list until the next tick because callers invoke this phase before unit
    turns.
    """
    units = {unit['id']: unit for unit in state['units']}
    remaining_projectiles = []
    for projectile in state['projectiles']:
        target = units.get(projectile['target'])
        if target is None or target['hp'] <= 0:
            continue

        remaining = math.hypot(
            projectile['x'] - target['x'],
            projectile['z'] - target['z'],
        )
        travel = projectile['speed'] * DT
        if remaining <= travel + _EPSILON:
            # The attacker remains available in the retained unit list even
            # when it died after launching this shot.
            attacker = units.get(projectile['attacker'])
            if attacker is not None:
                _apply_damage(state, attacker, target, projectile['attack'], 'ranged')
            continue

        # remaining is positive here, so this is safe and homes on the
        # target's *current* position rather than its launch position.
        fraction = travel / remaining
        projectile['x'] += (target['x'] - projectile['x']) * fraction
        projectile['z'] += (target['z'] - projectile['z']) * fraction
        remaining_projectiles.append(projectile)
    state['projectiles'] = remaining_projectiles


def _turn(state, unit):
    if unit['hp'] <= 0:
        return
    target = _living_target(state, unit)
    if target is None:
        return

    separation = distance(unit, target)
    if separation > unit['range'] + _EPSILON:
        # An outside-range turn is exclusively a movement turn.  It never
        # attacks, including when movement reaches the edge of attack range.
        amount = min(unit['speed'] * DT, separation - unit['range'])
        if separation > 0:
            scale = amount / separation
            x = unit['x'] + (target['x'] - unit['x']) * scale
            z = unit['z'] + (target['z'] - unit['z']) * scale
            if not _blocked(state, unit, x, z):
                unit['x'] = x
                unit['z'] = z
        return

    if state['tick'] < unit['next_attack']:
        return

    # Cooldown is consumed by the attack itself, even when this hit kills its
    # target.  A replacement target is considered on a later unit turn/tick.
    unit['next_attack'] = state['tick'] + unit['cooldown']
    if unit['kind'] == 'ranged':
        _launch(state, unit, target)
    else:
        _apply_damage(state, unit, target, unit['attack'], 'melee')


def _finish(state):
    """Apply elimination before the tick-limit rule."""
    living_teams = {
        unit['team'] for unit in state['units'] if unit['hp'] > 0
    }
    if len(living_teams) <= 1 and not state['projectiles']:
        state['status'] = 'finished'
        state['winner'] = next(iter(living_teams), 'draw') if living_teams else 'draw'
        state['reason'] = 'elimination'
    elif state['tick'] >= state['max_ticks']:
        state['status'] = 'finished'
        state['winner'] = 'draw'
        state['reason'] = 'tick_limit'


def step(battle, ticks):
    """Advance at most ``ticks`` fixed turns, stopping at the first finish."""
    state = copy.deepcopy(battle)
    for _ in range(ticks):
        if state['status'] != 'running':
            break
        state['tick'] += 1
        # Old shots are resolved before any unit gets its turn.
        _advance_projectiles(state)
        # begin() and every persisted state use this ordering.  Sorting here
        # also makes the rule robust to hand-created/imported battle JSON.
        state['units'].sort(key=lambda unit: unit['id'])
        for unit in state['units']:
            _turn(state, unit)
        _finish(state)
    return state


# Small public aliases retained for callers that used the starter module's
# helper names while the implementation was being completed.
advance_projectiles = _advance_projectiles
turn = _turn
finish = _finish
