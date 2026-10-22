"""Provisional local entitlement lookup."""
def validate(records, identifier, key):
    return any(r['uuid'] == identifier for r in records)
