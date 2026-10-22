from copy import deepcopy
from fetcher import fetch_text as default_fetch_text
from feed_parser import parse_feed

def process_exhibition_action(state, action, fetch_text=None):
    out=deepcopy(state); out.setdefault("sources",{}); out.setdefault("exhibitions",{})
    if action.get("type")=="add_source":
        source=action.get("source",{})
        if not all(source.get(k) for k in ["source_id","museum","city","url","feed_type"]):
            out["error"]={"code":"invalid_source"}; return out
        row={k:deepcopy(source.get(k)) for k in ["source_id","museum","city","url","feed_type","last_fetch"]}
        out["sources"][row["source_id"]]=row; out["result"]=deepcopy(row)
        return out
    raise NotImplementedError("Complete synchronization and view actions")
