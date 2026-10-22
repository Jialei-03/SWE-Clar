"""Standard MIDI File loading, note pairing, and lossless event retention.

The application deliberately keeps the original MIDI representation small: note
messages are paired while loading, while every non-note message is retained at
its original absolute tick.  The performance pass can therefore replace only
attacks, releases, and velocities without reconstructing a tempo map or any
metadata from scratch.
"""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import mido


_DEFAULT_TEMPO = 500000  # microseconds per quarter note, as used by MIDI
_MAX_SECONDS = Fraction(120, 1)


@dataclass(frozen=True)
class Note:
    """One paired source note.

    ``ordinal`` is the zero-based positive-velocity note-on ordinal within the
    source track.  The two indexes refer to positions in that original track
    and are used only to make same-tick output ordering deterministic.
    """

    track: int
    ordinal: int
    channel: int
    pitch: int
    velocity: int
    start: int
    end: int
    on_index: int
    off_index: int


@dataclass
class Song:
    kind: int
    ticks_per_beat: int
    tracks: list
    notes: list[Note]


def _absolute_events(midi):
    """Return ``(tick, track, event_index, message)`` for all source events."""
    events = []
    for track_number, track in enumerate(midi.tracks):
        absolute = 0
        for event_index, message in enumerate(track):
            # Parsed SMF delta times are integers, but explicitly checking the
            # invariant keeps malformed or hand-built Mido objects from
            # producing negative output deltas.
            delta = message.time
            if not isinstance(delta, int) or isinstance(delta, bool) or delta < 0:
                raise ValueError('MIDI event times must be non-negative ticks')
            absolute += delta
            events.append((absolute, track_number, event_index, message))
    return events


def _validate_duration(events, ticks_per_beat):
    """Validate the source timeline against the 120 second contract.

    Tempo messages are global in a Standard MIDI File.  The ordering here is
    the same deterministic tick/track/event ordering used by the protected
    render adapter.  ``Fraction`` avoids rounding a boundary at exactly 120
    seconds.
    """
    elapsed = Fraction(0, 1)
    last_tick = 0
    tempo = _DEFAULT_TEMPO
    for tick, _track, _index, message in sorted(events, key=lambda row: row[:3]):
        elapsed += Fraction((tick - last_tick) * tempo,
                            ticks_per_beat * 1_000_000)
        if elapsed > _MAX_SECONDS:
            raise ValueError('MIDI duration exceeds 120 seconds')
        last_tick = tick
        if message.type == 'set_tempo':
            if message.tempo <= 0:
                raise ValueError('Tempo must be positive')
            tempo = message.tempo


def load(path):
    """Load and validate one supported SMF.

    Note pairing is intentionally performed independently for each source
    track.  A positive note-on while its key is active is rejected rather than
    being implicitly stacked, which is the input contract's no-overlap rule.
    """
    midi = mido.MidiFile(str(path))
    if midi.type not in (0, 1):
        raise ValueError('Only SMF type 0/1 is supported')
    if midi.type == 0 and len(midi.tracks) != 1:
        raise ValueError('SMF type 0 must contain one track')
    if not isinstance(midi.ticks_per_beat, int) or midi.ticks_per_beat <= 0:
        raise ValueError('Only positive PPQN timing is supported')

    events = _absolute_events(midi)
    _validate_duration(events, midi.ticks_per_beat)

    tracks = []
    notes = []
    for track_number, track in enumerate(midi.tracks):
        absolute = 0
        ordinal = 0
        active = {}
        retained = []
        for index, message in enumerate(track):
            absolute += message.time
            if message.type == 'set_tempo':
                if message.tempo <= 0:
                    raise ValueError('Tempo must be positive')

            if message.type not in ('note_on', 'note_off'):
                # Copy now so later serialization cannot mutate the parsed
                # source object.  Its absolute tick and source index are kept.
                retained.append((absolute, index, message.copy()))
                continue

            if message.channel == 9:
                raise ValueError('Percussion channel is outside this contract')

            key = (message.channel, message.note)
            is_attack = message.type == 'note_on' and message.velocity > 0
            if is_attack:
                if key in active:
                    raise ValueError('Overlapping same-key notes are not supported')
                active[key] = (absolute, message.velocity, ordinal, index)
                ordinal += 1
                if ordinal > 10000:
                    raise ValueError('Input must contain at most 10000 notes')
            else:
                if key not in active:
                    raise ValueError('Unmatched note release')
                start, velocity, number, on_index = active.pop(key)
                if absolute <= start:
                    raise ValueError('Notes must have positive tick duration')
                notes.append(Note(track_number, number, key[0], key[1], velocity,
                                  start, absolute, on_index, index))

        if active:
            raise ValueError('Unterminated note')
        tracks.append(retained)

    if not 0 < len(notes) <= 10000:
        raise ValueError('Input must contain 1 to 10000 notes')

    # Pairing proceeds in source-track ordinal order.  This also makes the
    # previous-note lookup in the transformation independent of track layout.
    notes.sort(key=lambda note: (note.track, note.ordinal))
    return Song(midi.type, midi.ticks_per_beat, tracks, notes)


@dataclass(frozen=True)
class _OutputEvent:
    """An absolute-time event in the transformed track timeline.

    Keeping the ordering fields beside the message makes the serialization
    pass independent of the source representation.  In particular, note
    releases and attacks can be inserted into a track without changing the
    ordering of the retained metadata at a shared tick.
    """

    tick: int
    priority: int
    source_index: int
    note_ordinal: int
    serial: int
    message: object

    def sort_key(self):
        return (self.tick, self.priority, self.source_index,
                self.note_ordinal, self.serial)


def _track_output_events(retained, track_notes):
    """Build one absolute-time output timeline from source and note events."""
    events = []
    serial = 0

    for tick, source_index, message in retained:
        # Priority 1 places metadata between releases and attacks at a shared
        # tick, while source_index retains the original metadata order.
        events.append(_OutputEvent(tick, 1, source_index, 0, serial,
                                   message.copy()))
        serial += 1

    for note in track_notes:
        # Releases sort before attacks at a shared tick.  The source indexes
        # preserve the original ordering of otherwise simultaneous messages.
        events.append(_OutputEvent(
            note.end, 0, note.off_index, note.ordinal, serial,
            mido.Message('note_off', channel=note.channel,
                         note=note.pitch, velocity=0)))
        serial += 1
        events.append(_OutputEvent(
            note.start, 2, note.on_index, note.ordinal, serial,
            mido.Message('note_on', channel=note.channel,
                         note=note.pitch, velocity=note.velocity)))
        serial += 1

    return events


def _encode_track(events):
    """Turn an absolute-time event timeline into a Mido track."""
    track = mido.MidiTrack()
    previous_tick = 0
    for event in sorted(events, key=lambda item: item.sort_key()):
        if event.tick < previous_tick:
            raise ValueError('MIDI events are not in tick order')
        track.append(event.message.copy(time=event.tick - previous_tick))
        previous_tick = event.tick
    return track


def save(song, notes, path):
    """Write a genuine SMF with transformed notes and original non-note data."""
    notes_by_track = [[] for _ in song.tracks]
    for note in notes:
        notes_by_track[note.track].append(note)

    midi = mido.MidiFile(type=song.kind, ticks_per_beat=song.ticks_per_beat)
    for retained, track_notes in zip(song.tracks, notes_by_track):
        midi.tracks.append(_encode_track(
            _track_output_events(retained, track_notes)))
    midi.save(str(Path(path)))
