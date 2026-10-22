"""SMF loading, explicit note pairing, and lossless non-note event retention."""
from dataclasses import dataclass
from pathlib import Path
import mido


@dataclass(frozen=True)
class Note:
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


def load(path):
    midi = mido.MidiFile(str(path))
    if midi.type not in (0, 1) or midi.ticks_per_beat <= 0:
        raise ValueError('Only SMF type 0/1 with positive PPQN is supported')
    tracks, notes = [], []
    for track_number, track in enumerate(midi.tracks):
        absolute = ordinal = 0
        active = {}
        retained = []
        for index, message in enumerate(track):
            absolute += message.time
            if message.type == 'set_tempo' and message.tempo <= 0:
                raise ValueError('Tempo must be positive')
            if message.type not in ('note_on', 'note_off'):
                retained.append((absolute, index, message.copy()))
                continue
            if message.channel == 9:
                raise ValueError('Percussion channel is outside this piano input contract')
            key = (message.channel, message.note)
            if message.type == 'note_on' and message.velocity > 0:
                if key in active:
                    raise ValueError('Overlapping same-key notes are not supported')
                active[key] = (absolute, message.velocity, ordinal, index)
                ordinal += 1
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
    if sum(message.time for message in midi) > 120:
        raise ValueError('Input exceeds 120 seconds')
    notes.sort(key=lambda n: (n.track, n.ordinal))
    return Song(midi.type, midi.ticks_per_beat, tracks, notes)


def save(song, notes, path):
    events = [[(tick, 1, index, message.copy()) for tick, index, message in track]
              for track in song.tracks]
    for note in notes:
        events[note.track].extend([
            (note.start, 2, note.on_index, mido.Message('note_on', channel=note.channel,
                                                    note=note.pitch, velocity=note.velocity)),
            (note.end, 0, note.off_index, mido.Message('note_off', channel=note.channel,
                                                   note=note.pitch, velocity=0)),
        ])
    midi = mido.MidiFile(type=song.kind, ticks_per_beat=song.ticks_per_beat)
    for track_events in events:
        track = mido.MidiTrack()
        previous = 0
        for tick, _, _, message in sorted(track_events, key=lambda row: row[:3]):
            track.append(message.copy(time=tick-previous))
            previous = tick
        midi.tracks.append(track)
    midi.save(str(Path(path)))
