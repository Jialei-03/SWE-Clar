"""Server-side relationship, discovery, group and membership policies."""
from collections import deque
import json
import math


def blocked(db, actor, target):
    """Whether actor has blocked target (one direction only)."""
    return bool(
        db.execute(
            'SELECT 1 FROM blocks WHERE actor=? AND target=?',
            (actor, target),
        ).fetchone()
    )


def blocked_either(db, first, second):
    return blocked(db, first, second) or blocked(db, second, first)


def unblocked_pair(db, first, second):
    return not blocked_either(db, first, second)


def _accepted_graph(db):
    """Build the accepted, currently usable undirected graph.

    A connection is an edge only while neither endpoint blocks the other.
    Blocked users may still occur as intermediate vertices when an available
    path reaches them through another edge; the rule removes edges, rather
    than removing vertices from the graph.
    """
    graph = {}
    for connection in db.execute(
        'SELECT a,b FROM connections WHERE accepted=1'
    ):
        left, right = connection['a'], connection['b']
        if blocked_either(db, left, right):
            continue
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    return graph


def _degrees_from(db, actor, maximum=6):
    graph = _accepted_graph(db)
    distances = {actor: 0}
    queue = deque([actor])
    while queue:
        current = queue.popleft()
        distance = distances[current]
        if distance >= maximum:
            continue
        for neighbor in graph.get(current, ()):
            if neighbor not in distances:
                distances[neighbor] = distance + 1
                queue.append(neighbor)
    return distances


def matches(db, actor, radius, role):
    source = db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone()
    # The authenticated actor is always a real user, but retaining this guard
    # makes the policy safe when called independently.
    if source is None:
        return []

    source_interests = set(json.loads(source['interests']))
    degrees = _degrees_from(db, actor)
    result = []
    for candidate in db.execute('SELECT * FROM users'):
        candidate_id = candidate['id']
        if candidate_id == actor:
            continue
        if role != 'all' and candidate['role'] != role:
            continue
        if blocked_either(db, actor, candidate_id):
            continue

        distance = math.hypot(
            candidate['x'] - source['x'], candidate['y'] - source['y']
        )
        # The boundary is inclusive and distance remains unrounded in the
        # returned record and in the ordering comparison.
        if distance > radius:
            continue
        shared = len(source_interests & set(json.loads(candidate['interests'])))
        degree = degrees.get(candidate_id, 7)
        result.append(
            {
                'id': candidate_id,
                'display': candidate['display'],
                'role': candidate['role'],
                'shared': shared,
                'degree': degree,
                'distance': distance,
            }
        )

    result.sort(key=lambda item: (-item['shared'], item['degree'], item['distance'], item['id']))
    return result


def connection_allowed(db, actor, target, decision, existing):
    """Check a request/accept operation without changing any state."""
    if blocked_either(db, actor, target):
        return False

    if decision == 'request':
        # A second request from either endpoint is an idempotent no-op.  It is
        # still subject to the current blocking rule above.
        return True

    # Acceptance requires a connection request to exist.  The original
    # requester may never approve their own request.  Once accepted, only the
    # original recipient can repeat the accept operation idempotently.
    if existing is None:
        return False
    if existing['requester'] == actor:
        return False
    return True


def message_allowed(db, actor, target):
    connection = db.execute(
        '''SELECT accepted FROM connections
           WHERE (a=? AND b=?) OR (a=? AND b=?)''',
        (actor, target, target, actor),
    ).fetchone()
    return bool(
        connection is not None
        and connection['accepted']
        and unblocked_pair(db, actor, target)
    )


def _member(db, group_id, user_id):
    return bool(
        db.execute(
            'SELECT 1 FROM members WHERE group_id=? AND user_id=?',
            (group_id, user_id),
        ).fetchone()
    )


def invite_allowed(db, actor, target, group):
    return (
        actor == group['owner']
        and unblocked_pair(db, group['owner'], target)
    )


def post_allowed(db, actor, group):
    return (
        _member(db, group['id'], actor)
        and unblocked_pair(db, actor, group['owner'])
    )


def post_visible(db, actor, post, group):
    """Whether actor can see a post under dashboard/group visibility rules."""
    return (
        post_allowed(db, actor, group)
        and unblocked_pair(db, actor, post['author'])
    )


def like_allowed(db, actor, post, group):
    # A like is a write on a visible post.  The explicit author check is kept
    # in addition to post_visible so both block directions are enforced even
    # if this function is reused outside the dashboard.
    return (
        post_visible(db, actor, post, group)
        and unblocked_pair(db, actor, post['author'])
    )


def store_like(db, actor, post):
    db.execute(
        'INSERT OR IGNORE INTO likes(post_id,user_id) VALUES(?,?)',
        (post, actor),
    )


def membership_allowed(user, receipt):
    if receipt.get('user_id') != user['id']:
        return False
    if user['role'] == 'user':
        allowed = {'free', 'plus'}
    elif user['role'] == 'business':
        allowed = {'free', 'local', 'regional', 'global'}
    else:
        return False
    return receipt.get('plan') in allowed


def apply_membership(db, user, receipt):
    """Record a first redemption and replace the active plan.

    The caller owns an IMMEDIATE transaction.  Returning False means a
    redemption was already consumed by this same account and must not restore
    the old plan on replay.  A receipt consumed by another account is not
    applied either.
    """
    consumed = db.execute(
        'SELECT user_id FROM payments WHERE receipt_id=?',
        (receipt['id'],),
    ).fetchone()
    if consumed is not None:
        return consumed['user_id'] == user['id']

    db.execute(
        'INSERT INTO payments(receipt_id,user_id,plan) VALUES(?,?,?)',
        (receipt['id'], user['id'], receipt['plan']),
    )
    db.execute(
        'UPDATE users SET plan=? WHERE id=?',
        (receipt['plan'], user['id']),
    )
    return True


def featured_allowed(user):
    return (
        user['role'] == 'business'
        and user['plan'] in {'local', 'regional', 'global'}
    )
