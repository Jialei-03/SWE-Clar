from copy import deepcopy

def _err(state, code):
    out = deepcopy(state); out["error"] = {"code": code}; return out

def _visible(user, entity):
    if user.get("role") == "tenant_admin": return True
    return entity.get("company_id") == user.get("company_id")

def process_iot_action(state: dict, action: dict) -> dict:
    out = deepcopy(state) if isinstance(state, dict) else {}; a = deepcopy(action) if isinstance(action, dict) else {}; kind = a.get("type")
    for key, default in (("users", {}), ("entities", {}), ("devices", {}), ("topics", {}), ("telemetry", {}), ("rules", {}), ("alarms", {})):
        out.setdefault(key, default)
    if kind == "create_entity":
        actor = out["users"].get(a.get("actor_id")); etype = a.get("entity_type"); eid = str(a.get("entity_id", "")).strip()
        allowed = actor and ((actor.get("role") == "tenant_admin" and etype in {"reseller", "company"}) or (actor.get("role") == "company_admin" and etype == "device" and a.get("company_id") == actor.get("company_id")))
        if not allowed or not eid or eid in out["entities"]: return _err(out, "create_denied")
        row = {"type": etype, "name": a.get("name"), "company_id": a.get("company_id")}; out["entities"][eid] = row
        if etype == "device": out["devices"][eid] = deepcopy(row)
        out["result"] = {"entity_id": eid}
    elif kind == "update_device":
        actor = out["users"].get(a.get("actor_id")); dev = out["devices"].get(a.get("device_id"))
        if not actor or not dev or not _visible(actor, dev) or actor.get("role") not in {"tenant_admin", "company_admin"}: return _err(out, "update_denied")
        dev.update(deepcopy(a.get("changes", {}))); out["entities"][a["device_id"]] = deepcopy(dev); out["result"] = deepcopy(dev)
    elif kind == "ingest":
        device_id = out["topics"].get(a.get("topic")); payload = a.get("payload"); ts = a.get("timestamp")
        if device_id not in out["devices"] or not isinstance(payload, dict) or isinstance(ts, bool) or not isinstance(ts, (int, float)) or any(not isinstance(k, str) for k in payload): return _err(out, "invalid_telemetry")
        for key, value in payload.items():
            out["telemetry"].setdefault(device_id, {}).setdefault(key, []).append({"timestamp": ts, "value": value}); out["telemetry"][device_id][key].sort(key=lambda x: x["timestamp"])
        for rid, rule in out["rules"].items():
            value = payload.get(rule.get("key")); triggered = isinstance(value, (int, float)) and ((rule.get("operator") == "gt" and value > rule.get("threshold")) or (rule.get("operator") == "lt" and value < rule.get("threshold")))
            aid = f"{device_id}:{rid}"
            if triggered and aid not in out["alarms"]: out["alarms"][aid] = {"device_id": device_id, "rule_id": rid, "status": "active", "value": value, "timestamp": ts}
        out["result"] = {"device_id": device_id, "keys": sorted(payload)}
    elif kind == "aggregate":
        rows = [x["value"] for x in out["telemetry"].get(a.get("device_id"), {}).get(a.get("key"), []) if isinstance(x["value"], (int, float)) and a.get("start") <= x["timestamp"] <= a.get("end")]
        if not rows: return _err(out, "not_found")
        out["result"] = {"count": len(rows), "min": min(rows), "max": max(rows), "mean": sum(rows) / len(rows)}
    elif kind in {"ack_alarm", "clear_alarm"}:
        alarm = out["alarms"].get(a.get("alarm_id"))
        if not alarm: return _err(out, "unknown_alarm")
        alarm["status"] = "acknowledged" if kind == "ack_alarm" else "cleared"; out["result"] = deepcopy(alarm)
    elif kind == "dashboard":
        user = out["users"].get(a.get("user_id"))
        if not user: return _err(out, "unknown_user")
        devices = [{"device_id": i, **deepcopy(v)} for i, v in out["devices"].items() if _visible(user, v)]; visible_ids = {x["device_id"] for x in devices}; alarms = [{"alarm_id": i, **deepcopy(v)} for i, v in out["alarms"].items() if v["device_id"] in visible_ids and v["status"] != "cleared"]
        out["result"] = {"devices": sorted(devices, key=lambda x: x["device_id"]), "alarms": sorted(alarms, key=lambda x: x["alarm_id"])}
    else: return _err(out, "unknown_action")
    out.pop("error", None); return out

def ingest_mqtt(state,host,port,max_messages=1,timeout=2):
    raise NotImplementedError("Subscribe and process actual MQTT publications")
