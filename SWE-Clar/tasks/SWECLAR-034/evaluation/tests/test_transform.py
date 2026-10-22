import json
import os
from copy import deepcopy
from pathlib import Path
import sys


from candidate_proxy import transform


FIELDS = (
    "title",
    "property_type",
    "address",
    "max_persons",
    "contact_name",
    "contact_phone",
    "url",
    "lat",
    "lng",
    "pool",
)


def test_ru_001_normalized_record_shape_order_determinism_and_nonmutation():
    rows = [
        {
            "title": "First",
            "property_type": "villa",
            "address": "Example Street",
            "max_persons": 6,
            "contact_name": "Ada",
            "contact_phone": "00000001",
            "url": "https://example.test/first",
            "lat": 39.8,
            "lng": 19.6,
            "pool": "yes",
            "private_note": "must not leak",
        },
        {
            "title": "Second",
            "property_type": "apartment",
            "address": "Other Street",
            "max_persons": 2,
            "contact_name": "Grace",
            "contact_phone": "00000002",
            "url": "https://example.test/second",
            "lat": 41.0,
            "lng": -4.3,
            "pool": "no",
        },
    ]
    before = deepcopy(rows)

    got = transform(rows)
    replay = transform(rows)

    assert rows == before
    assert got == replay
    assert json.loads(json.dumps(got)) == got
    assert isinstance(got, list) and len(got) == len(rows)
    assert [record["title"] for record in got] == ["First", "Second"]
    expected_fields = set(FIELDS)
    assert all(set(row) == expected_fields for row in got)
    for source, record in zip(rows, got):
        for field in (name for name in FIELDS if name not in {"contact_phone", "url"}):
            assert type(record[field]) is type(source[field]), (field, type(record[field]), type(source[field]))
            assert record[field] == source[field]
    assert transform([]) == []


def test_ru_002_url_fallback_phone_normalization_and_missing_values():
    got = transform(
        [
            {
                "title": "Explicit",
                "url": "https://example.test/final",
                "uri": "https://example.test/fallback",
                "contact_phone": "+00 (00) 001, ext. 2 / +00-00-002, none",
            },
            {
                "title": "Fallback",
                "uri": "https://example.test/source",
                "contact_phone": 1234,
            },
            {
                "title": "Empty explicit URL",
                "url": "",
                "uri": "https://example.test/empty-fallback",
                "contact_phone": None,
            },
            {"title": "Missing"},
        ]
    )

    assert got[0]["url"] == "https://example.test/final"
    assert got[0]["contact_phone"] == "0000001, 20000002"
    assert got[1]["url"] == "https://example.test/source"
    assert got[1]["contact_phone"] == "1234"
    assert got[2]["url"] == "https://example.test/empty-fallback"
    assert got[2]["contact_phone"] == ""
    missing = got[3]
    assert missing["contact_phone"] == ""
    assert missing["url"] == ""


def test_ru_002_all_missing_fields_use_empty_string():
    fields = {'title','property_type','address','max_persons','contact_name',
              'contact_phone','url','lat','lng','pool'}
    assert transform([{}]) == [{field: '' for field in fields}]
