"""Pure family-policy operations used by the HTTP service.

The service keeps its state as one JSON object.  This module deliberately
operates on a deep copy of that object: an action is either represented by a
new state or by an error response, and callers never observe a partial
mutation of their input.
"""
from copy import deepcopy
import math


_REQUIRED_STATE = (
    ('users', {}),
    ('devices', {}),
    ('policies', {}),
    ('activity', []),
    ('notifications', []),
    ('audit', []),
    ('policy_versions', {}),
)


def _nonempty_string(value):
    return isinstance(value, str) and bool(value)


def _finite_nonnegative_number(value):
    """Return whether *value* is a JSON-style finite, non-negative number."""
    # bool is an int subclass, but is not a minute total or a limit.  Python
    # integers have arbitrary precision and are finite by construction; only
    # floating-point values need an isfinite check.
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    if not isinstance(value, float):
        return False
    return math.isfinite(value) and value >= 0


def _normalise_host(value):
    """Return the canonical form of a supported host, or ``None``.

    The input contract intentionally describes hosts rather than URLs.  In
    particular, a slash, a port, whitespace, an empty label, or a non-ASCII
    character is not part of a host accepted by this component.  A single
    final dot is DNS presentation syntax and is ignored for comparisons.
    """
    if not isinstance(value, str) or not value or not value.isascii():
        return None
    if value.endswith('.'):
        value = value[:-1]
        if not value:
            return None
    labels = value.split('.')
    if not labels:
        return None
    for label in labels:
        if not label:
            return None
        # Do not use str.isalnum alone: it accepts many non-ASCII letters.
        if any(not (('a' <= char <= 'z') or
                    ('A' <= char <= 'Z') or
                    ('0' <= char <= '9') or char == '-')
               for char in label):
            return None
    return value.lower()


def _ensure_state_shape(state):
    """Create the documented empty collections when they are absent."""
    for key, default in _REQUIRED_STATE:
        if key not in state:
            state[key] = deepcopy(default)
    # A normal seed always has these types.  Treat a malformed collection as
    # empty rather than allowing an untrusted action to raise an exception.
    if not isinstance(state.get('users'), dict):
        state['users'] = {}
    if not isinstance(state.get('devices'), dict):
        state['devices'] = {}
    if not isinstance(state.get('policies'), dict):
        state['policies'] = {}
    if not isinstance(state.get('activity'), list):
        state['activity'] = []
    if not isinstance(state.get('notifications'), list):
        state['notifications'] = []
    if not isinstance(state.get('audit'), list):
        state['audit'] = []


def _device_has_owner(devices, owner_id):
    for record in devices.values():
        if isinstance(record, dict) and record.get('owner_id') == owner_id:
            return True
    return False


def _can_set_policy(actor_id, device):
    if not _nonempty_string(actor_id) or not isinstance(device, dict):
        return False
    mode = device.get('mode')
    if mode == 'self':
        return device.get('owner_id') == actor_id
    if mode == 'parent_child':
        return device.get('parent_id') == actor_id
    return False


def _valid_policy_payload(action):
    """Validate and return a copied policy payload, or ``None``."""
    blocked_domains = action.get('blocked_domains')
    blocked_apps = action.get('blocked_apps')
    limits = action.get('app_daily_limits')

    if not isinstance(blocked_domains, list) or not isinstance(blocked_apps, list):
        return None
    if not isinstance(limits, dict):
        return None

    for domain in blocked_domains:
        if not _nonempty_string(domain) or _normalise_host(domain) is None:
            return None
    for app in blocked_apps:
        if not _nonempty_string(app):
            return None
    for app, limit in limits.items():
        if not _nonempty_string(app) or not _finite_nonnegative_number(limit):
            return None

    # The action is JSON data, but deepcopy also keeps this function safe for
    # direct Python callers that retain their input after the call.
    return {
        'blocked_domains': deepcopy(blocked_domains),
        'blocked_apps': deepcopy(blocked_apps),
        'app_daily_limits': deepcopy(limits),
    }


def _policy_decision(policy, target_type, target, used_minutes):
    """Return the denial reason, or ``allowed`` for an allowed request."""
    if not isinstance(policy, dict):
        policy = {}

    if target_type == 'domain':
        blocked_domains = policy.get('blocked_domains', [])
        if not isinstance(blocked_domains, list):
            blocked_domains = []
        for blocked in blocked_domains:
            blocked_canonical = _normalise_host(blocked)
            if blocked_canonical is None:
                continue
            if (target == blocked_canonical or
                    target.endswith('.' + blocked_canonical)):
                return 'blocked_domain'
        return 'allowed'

    blocked_apps = policy.get('blocked_apps', [])
    if isinstance(blocked_apps, list) and target in blocked_apps:
        return 'blocked_app'

    limits = policy.get('app_daily_limits', {})
    if isinstance(limits, dict) and target in limits:
        limit = limits[target]
        # Policies created through set_policy always pass this check.  The
        # defensive test keeps a hand-written seed from taking down access
        # checks; an invalid stored limit is ignored rather than enforced.
        if _finite_nonnegative_number(limit) and used_minutes >= limit:
            return 'daily_limit'
    return 'allowed'


def _activity_fingerprint(record):
    """Get the retry identity stored in an activity record.

    ``used_minutes`` is an intentionally additive metadata field.  Older or
    hand-written activity records did not have it, and are interpreted as a
    zero-minute event for backwards compatibility.
    """
    if not isinstance(record, dict):
        return None
    device_id = record.get('device_id')
    target_type = record.get('target_type')
    target = record.get('target')
    if not (_nonempty_string(device_id) and
            target_type in ('domain', 'app') and
            _nonempty_string(target)):
        return None
    if target_type == 'domain':
        target = _normalise_host(target)
        if target is None:
            return None
    used_minutes = record.get('used_minutes', 0)
    if not _finite_nonnegative_number(used_minutes):
        return None
    return (device_id, target_type, target, used_minutes, record.get('policy_version', 0))


def _same_fingerprint(left, right):
    # A tuple comparison makes 1 and 1.0 equivalent, as they are equivalent
    # JSON numeric values for the purposes of a retry.
    return left is not None and right is not None and left == right


def _decision_from_activity(record):
    reason = record.get('reason')
    return {'allowed': False, 'reason': reason}


def _check_existing_denial(activity, event_id, fingerprint):
    """Return (decision, conflict) for an already-seen denied event."""
    # An event id is global among denied events.  Check it first so reusing an
    # id for a different event cannot be hidden by another retry fingerprint.
    for record in activity:
        if not isinstance(record, dict) or record.get('event_id') != event_id:
            continue
        old_fingerprint = _activity_fingerprint(record)
        if _same_fingerprint(old_fingerprint, fingerprint):
            return _decision_from_activity(record), False
        return None, True

    # Retries are also recognised by their canonical device/target/usage
    # identity.  This covers a retry whose transport supplied a fresh event
    # id while avoiding a second local evidence record.
    for record in activity:
        old_fingerprint = _activity_fingerprint(record)
        if _same_fingerprint(old_fingerprint, fingerprint):
            return _decision_from_activity(record), False
    return None, False


def _configure_mode(state, action, error, users, devices):
    user_id = action.get('user_id')
    device_id = action.get('device_id')
    mode = action.get('mode')

    if (not _nonempty_string(user_id) or user_id not in users or
            not _nonempty_string(device_id) or device_id in devices):
        return error('link_denied')

    if mode == 'self':
        # A child has one linked device regardless of whether it was first
        # configured by the child or by its parent.  Parents are not given an
        # artificial one-device restriction by the public contract.
        profile = users.get(user_id)
        if (isinstance(profile, dict) and profile.get('role') == 'child' and
                _device_has_owner(devices, user_id)):
            return error('link_denied')
        devices[device_id] = {'owner_id': user_id, 'mode': 'self'}
    elif mode == 'parent_child':
        child_id = action.get('child_id')
        parent_profile = users.get(user_id)
        child_profile = users.get(child_id) if _nonempty_string(child_id) else None
        if (not isinstance(parent_profile, dict) or
                parent_profile.get('role') != 'parent' or
                not isinstance(child_profile, dict) or
                child_profile.get('role') != 'child' or
                child_profile.get('parent_id') != user_id or
                _device_has_owner(devices, child_id)):
            return error('link_denied')
        devices[device_id] = {
            'owner_id': child_id,
            'parent_id': user_id,
            'mode': 'parent_child',
        }
    else:
        return error('link_denied')

    state['result'] = {'device_id': device_id}
    return state


def _set_policy(state, action, error, devices, policies):
    actor_id = action.get('actor_id')
    device_id = action.get('device_id')
    device = devices.get(device_id) if _nonempty_string(device_id) else None

    # Authorization is checked before accepting policy contents.  In
    # particular, an actor cannot use malformed policy data to distinguish an
    # inaccessible device from an accessible one.
    if not _can_set_policy(actor_id, device):
        return error('policy_denied')

    policy = _valid_policy_payload(action)
    if policy is None:
        return error('invalid_policy')
    policies[device_id] = policy
    state['policy_versions'][device_id] = state['policy_versions'].get(device_id, 0) + 1
    return state


def _check_access(state, action, error, devices, policies, activity,
                  notifications):
    device_id = action.get('device_id')
    event_id = action.get('event_id')
    target_type = action.get('target_type')
    target = action.get('target')
    used_minutes = action.get('used_minutes', 0)

    device = devices.get(device_id) if _nonempty_string(device_id) else None
    if not isinstance(device, dict):
        return error('invalid_access_check')
    if not _nonempty_string(event_id):
        return error('invalid_access_check')
    if target_type not in ('domain', 'app') or not _nonempty_string(target):
        return error('invalid_access_check')
    if not _finite_nonnegative_number(used_minutes):
        return error('invalid_access_check')

    if target_type == 'domain':
        canonical_target = _normalise_host(target)
        if canonical_target is None:
            return error('invalid_access_check')
    else:
        # App identifiers are deliberately case-sensitive.
        canonical_target = target

    policy_version = state['policy_versions'].get(device_id, 0)
    fingerprint = (device_id, target_type, canonical_target, used_minutes, policy_version)
    previous_decision, conflict = _check_existing_denial(
        activity, event_id, fingerprint)
    if conflict:
        return error('event_conflict')
    if previous_decision is not None:
        state['result'] = previous_decision
        return state

    policy = policies.get(device_id)
    reason = _policy_decision(policy, target_type, canonical_target, used_minutes)
    decision = {'allowed': reason == 'allowed', 'reason': reason}
    state['result'] = decision
    if reason == 'allowed':
        return state

    # Keep the requested target as evidence (rather than silently rewriting
    # what the caller sent); canonicalisation is used for matching/retries.
    activity_record = {
        'event_id': event_id,
        'device_id': device_id,
        'target_type': target_type,
        'target': target,
        'reason': reason,
        # This additive field makes retry identity durable across restarts.
        'used_minutes': used_minutes,
        'policy_version': policy_version,
    }
    activity.append(activity_record)

    parent_id = device.get('parent_id')
    if (device.get('mode') == 'parent_child' and
            _nonempty_string(parent_id)):
        notifications.append({
            'event_id': event_id,
            'device_id': device_id,
            'parent_id': parent_id,
            'reason': reason,
        })
    return state


def _report(state, action, error, users, devices, activity):
    parent_id = action.get('parent_id')
    device_id = action.get('device_id')
    device = devices.get(device_id) if _nonempty_string(device_id) else None

    if (not _nonempty_string(parent_id) or not isinstance(device, dict) or
            device.get('mode') != 'parent_child' or
            device.get('parent_id') != parent_id):
        return error('report_denied')

    parent_profile = users.get(parent_id)
    if not isinstance(parent_profile, dict) or parent_profile.get('role') != 'parent':
        return error('report_denied')

    state['result'] = {
        'activity': deepcopy([
            record for record in activity
            if isinstance(record, dict) and record.get('device_id') == device_id
        ])
    }
    return state


def _delete_account(state, action, error, users, devices, policies,
                    activity, notifications, audit):
    user_id = action.get('user_id')
    if not _nonempty_string(user_id) or user_id not in users:
        return error('account_missing')

    # A user owns a self device or a child device; a parent controls every
    # parent-child device carrying its parent_id.  Take the set before any
    # collection is edited so all related durable evidence is removed.
    device_ids = {
        device_id for device_id, record in devices.items()
        if isinstance(record, dict) and
        (record.get('owner_id') == user_id or record.get('parent_id') == user_id)
    }

    for device_id in device_ids:
        devices.pop(device_id, None)
        policies.pop(device_id, None)
        state.get('policy_versions', {}).pop(device_id, None)

    def belongs_to_deleted_device(record):
        if not isinstance(record, dict):
            return False
        record_device_id = record.get('device_id')
        # JSON object keys (and therefore normal device IDs) are strings.  The
        # type guard also keeps a malformed historical record from raising an
        # unhandled TypeError while deleting an account.
        return (_nonempty_string(record_device_id) and
                record_device_id in device_ids)

    state['activity'] = [
        record for record in activity
        if not belongs_to_deleted_device(record)
    ]
    state['notifications'] = [
        record for record in notifications
        if not belongs_to_deleted_device(record)
    ]

    users.pop(user_id, None)
    # Direct children remain accounts, but their family link is severed.
    for profile in users.values():
        if isinstance(profile, dict) and profile.get('parent_id') == user_id:
            profile.pop('parent_id', None)

    # Existing audit entries naming the deleted subject are removed.  The new
    # entry intentionally contains no account or device identifier.
    state['audit'] = [
        record for record in audit
        if not (isinstance(record, dict) and record.get('subject') == user_id)
    ]
    state['audit'].append({'type': 'account_deleted', 'subject': 'redacted'})
    return state


def process_control_action(state, action):
    """Process one action without mutating ``state`` or ``action``."""
    if not isinstance(state, dict):
        return {'error': {'code': 'invalid_request'}}

    working = __import__('json').loads(__import__('json').dumps(state))
    # A result/error belongs only to an individual response and is never part
    # of the chainable persisted snapshot.
    working.pop('result', None)
    working.pop('error', None)
    _ensure_state_shape(working)

    def error(code):
        working['error'] = {'code': code}
        return working

    if not isinstance(action, dict):
        return error('invalid_request')

    kind = action.get('type')
    users = working['users']
    devices = working['devices']
    policies = working['policies']
    activity = working['activity']
    notifications = working['notifications']
    audit = working['audit']

    if kind == 'configure_mode':
        return _configure_mode(working, action, error, users, devices)
    if kind == 'set_policy':
        return _set_policy(working, action, error, devices, policies)
    if kind == 'check_access':
        return _check_access(working, action, error, devices, policies,
                             activity, notifications)
    if kind == 'report':
        return _report(working, action, error, users, devices, activity)
    if kind == 'delete_account':
        return _delete_account(working, action, error, users, devices,
                               policies, activity, notifications, audit)
    return error('unsupported_action')
