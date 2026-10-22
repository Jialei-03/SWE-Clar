"""Public state-transition entry point and JSON command-line adapter."""
from copy import deepcopy
from accounts import apply_account
from commerce import apply_commerce


def process_membership_action(state: dict, action: dict) -> dict:
    # Work exclusively on copies so neither the state nor the command object
    # supplied by the caller can be changed by a transition.
    current = deepcopy(state)
    request = deepcopy(action)
    current.pop("result", None)
    current.pop("error", None)
    action_type = request.get("type") if isinstance(request, dict) else None
    if action_type in ("create_account", "delete_account"):
        return apply_account(current, request)
    return apply_commerce(current, request if isinstance(request, dict) else {})


if __name__ == "__main__":
    import json
    import sys
    request = json.load(sys.stdin)
    json.dump(process_membership_action(request["state"], request["action"]), sys.stdout, allow_nan=False)
    sys.stdout.write("\n")
