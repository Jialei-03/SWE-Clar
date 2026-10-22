"""Performance policy hook. The existing application preserves the input notes."""


def transform(song, seed, articulation):
    return list(song.notes)
