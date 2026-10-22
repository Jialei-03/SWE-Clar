"""Independent event-credit ledger extension point."""
from copy import deepcopy

def process_cashless_action(state: dict, action: dict, upload_events=None) -> dict:
    """Complete the ledger; preserve provided transports and console."""
    return deepcopy(state)
