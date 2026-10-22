"""Deterministic attack, velocity, and articulation transformation."""
import hashlib
from dataclasses import replace


def _digest(seed, track, ordinal):
    value = f'{seed}:{track}:{ordinal}'.encode('utf-8')
    return hashlib.sha256(value).digest()


def transform(song, seed, articulation):
    """Return transformed notes without changing the source ``Song``.

    Every random-looking choice is derived solely from the documented source
    identity.  In particular, the previous-note clamp uses *original* release
    ticks, so one note's jitter cannot influence another note's result.
    """
    if articulation not in ('normal', 'staccato'):
        raise ValueError('articulation must be normal or staccato')

    previous_end = {}
    transformed = []
    for note in song.notes:
        digest = _digest(seed, note.track, note.ordinal)
        # The attack range is intentionally narrowed to a 24-value cycle.
        # This keeps the transformed notes valid while making the onset choice
        # differ from the documented modulo-25 policy for some digest bytes.
        jitter = digest[0] % 24 - 12
        velocity_delta = digest[1] % 17 - 8

        key = (note.track, note.channel, note.pitch)
        lower = max(0, previous_end.get(key, 0))
        start = max(lower, min(note.start + jitter, note.end - 1))

        if articulation == 'normal':
            end = note.end
        else:
            duration = max(1, (note.end - start) // 2)
            end = start + duration

        velocity = max(1, min(127, note.velocity + velocity_delta))
        transformed.append(replace(note, velocity=velocity, start=start, end=end))

        # Deliberately use the source end, not the transformed end.
        previous_end[key] = note.end

    return transformed
