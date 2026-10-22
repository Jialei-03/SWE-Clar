"""Synthetic local entitlement lookup."""
import re


_UUID = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)


def validate(records, identifier, key):
    """Validate one submitted UUID/product-key pair without exposing records."""
    if not isinstance(identifier, str) or not isinstance(key, str):
        return False

    submitted_uuid = identifier.strip()
    submitted_key = key.strip()
    if _UUID.fullmatch(submitted_uuid) is None:
        return False
    submitted_uuid = submitted_uuid.lower()

    if not isinstance(records, list):
        return False
    for record in records:
        if not isinstance(record, dict):
            continue
        record_uuid = record.get('uuid')
        record_key = record.get('product_key')
        if (isinstance(record_uuid, str)
                and record_uuid.lower() == submitted_uuid
                and record_key == submitted_key
                and record.get('active') is True):
            return True
    return False
