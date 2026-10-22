from copy import deepcopy

def fail(state, code):
    out=deepcopy(state); out["error"]={"code":code}; return out

def process_smartlink_event(state: dict, event: dict, service=None) -> dict:
    out=deepcopy(state) if isinstance(state,dict) else {}; ev=deepcopy(event) if isinstance(event,dict) else {}; kind=ev.get("type")
    out.setdefault("smartlinks",{}); out.setdefault("oauth_states",{}); out.setdefault("spotify_users",{}); out.setdefault("clicks",{}); out.setdefault("streams",{}); out.setdefault("conversions",{}); out.setdefault("attribution_window",604800)
    if kind=="oauth_start":
        token=str(ev.get("state_token","")).strip(); user=str(ev.get("user_id","")).strip()
        if not token or not user or token in out["oauth_states"]: return fail(out,"invalid_oauth_start")
        out["oauth_states"][token]={"user_id":user,"consumed":False}; out["result"]={"state_token":token}
    elif kind=="oauth_complete":
        token=ev.get("state_token"); row=out["oauth_states"].get(token); code=str(ev.get("code","")).strip()
        if not row or row["consumed"] or not code: return fail(out,"invalid_oauth_callback")
        raise NotImplementedError("Exchange the code before authorizing the user")
    elif kind in {"click","stream","conversion"}:
        return fail(out,"not_implemented")
    elif kind=="status": out["result"]={"clicks":len(out["clicks"]),"attributed_streams":len(out["streams"]),"conversions":len(out["conversions"])}
    else: return fail(out,"unknown_event")
    out.pop("error",None); return out
