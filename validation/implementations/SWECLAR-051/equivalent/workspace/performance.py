"""Deterministic attack, velocity, and articulation transformation."""
import hashlib
from dataclasses import replace


def _digest(seed, track, ordinal):
    value = f'{seed}:{track}:{ordinal}'.encode('utf-8')
    return hashlib.sha256(value).digest()


def _attack_start(note, jitter, previous_end):
    """Clamp a jittered attack against the source-note safety interval."""
    key = (note.track, note.channel, note.pitch)
    lower = max(0, previous_end.get(key, 0))
    upper = note.end - 1
    candidate = note.start + jitter
    # The source pairing rules guarantee lower <= upper.  Written as two
    # explicit bounds rather than relying on nested min/max, this also makes
    # the interval used by the timing policy apparent.
    return max(lower, min(candidate, upper))


def _transform_one(note, seed, articulation, previous_end):
    """Transform one source note using state from earlier source notes."""
    digest = _digest(seed, note.track, note.ordinal)
    jitter = digest[0] % 25 - 12
    velocity_delta = digest[1] % 17 - 8
    start = _attack_start(note, jitter, previous_end)

    if articulation == 'normal':
        end = note.end
    else:
        duration = max(1, (note.end - start) // 2)
        end = start + duration

    velocity = max(1, min(127, note.velocity + velocity_delta))
    transformed = replace(note, velocity=velocity, start=start, end=end)

    # Deliberately record the source release.  A transformed release must not
    # affect the clamp for a later note with the same source key.
    previous_end[(note.track, note.channel, note.pitch)] = note.end
    return transformed


def transform(song, seed, articulation):
    """Return transformed notes without changing the source ``Song``.

    Every random-looking choice is derived solely from the documented source
    identity.  In particular, the previous-note clamp uses *original* release
    ticks, so one note's jitter cannot influence another note's result.
    """
    if articulation not in ('normal', 'staccato'):
        raise ValueError('articulation must be normal or staccato')

    previous_end = {}
    return [
        _transform_one(note, seed, articulation, previous_end)
        for note in song.notes
    ]
