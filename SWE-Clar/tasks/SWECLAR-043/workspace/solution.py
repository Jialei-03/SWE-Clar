"""Delivery workflow extension point; existing storage adapters are provided."""
from copy import deepcopy

def apply_delivery_event(order: dict, event: dict) -> dict:
    """Implement the disclosed deterministic delivery contract."""
    return deepcopy(order)
