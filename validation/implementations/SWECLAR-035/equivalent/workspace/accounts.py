"""Existing local account lifecycle. All identities are synthetic inputs."""


def apply_account(state, action):
    """Apply account creation or inactivation to an already-copied state."""
    user_id = action.get("user_id")
    users = state.get("users")

    if action.get("type") == "create_account":
        if not isinstance(users, dict):
            users = {}
            state["users"] = users
        if user_id not in users:
            # Deliberately select only account fields; an accidental card
            # object in the command is never persisted.
            users[user_id] = {
                "email": action.get("email", ""),
                "phone": action.get("phone", ""),
                "provider": action.get("provider", "email"),
                "status": "active",
                "membership": "free",
                "credits": 0,
            }
        state["result"] = {"user_id": user_id}
        return state

    if action.get("type") == "delete_account":
        if not isinstance(users, dict) or user_id not in users:
            state["error"] = {"code": "unknown_account"}
            return state
        users[user_id]["status"] = "inactive"
        state["result"] = {"user_id": user_id}
        return state

    state["error"] = {"code": "unknown_action"}
    return state
