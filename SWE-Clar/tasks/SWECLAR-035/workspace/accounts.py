"""Existing local account lifecycle. All identities are synthetic inputs."""
def apply_account(state, action):
    users = state.setdefault("users", {})
    uid = action["user_id"]
    if action["type"] == "create_account":
        if uid not in users:
            users[uid] = {"email": action.get("email", ""),
                          "phone": action.get("phone", ""),
                          "provider": action.get("provider", "email"),
                          "status": "active", "membership": "free", "credits": 0}
        state["result"] = {"user_id": uid}
    elif uid in users:
        users[uid]["status"] = "inactive"
        state["result"] = {"user_id": uid}
    else:
        state["error"] = {"code": "unknown_account"}
    return state
