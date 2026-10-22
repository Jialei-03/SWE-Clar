from copy import deepcopy
import hashlib
def _e(s,c):o=deepcopy(s);o["error"]={"code":c};return o
def process_field_action(state:dict,action:dict,store=None,transport=None)->dict:
 o=deepcopy(state) if isinstance(state,dict) else {};a=deepcopy(action) if isinstance(action,dict) else {};k=a.get("type")
 for x,d in (("users",{}),("sessions",{}),("assignments",{}),("remote_jobs",{}),("offline",{}),("queue",[]),("applied",[])):o.setdefault(x,d)
 o.setdefault("online",False);o.setdefault("last_up",None);o.setdefault("last_down",None)
 if k=="authenticate":
  uid=a.get("user_id");u=o["users"].get(uid);now=int(a.get("now",0));last=u.get("last_2fa") if u else None;need=last is None or now-int(last)>=14*86400
  if not u or hashlib.sha256(str(a.get("password","")).encode()).hexdigest()!=u.get("password_hash") or need and a.get("two_factor_code")!=u.get("two_factor_code"):return _e(o,"auth_denied")
  if need:u["last_2fa"]=now
  o["sessions"][uid]={"last_active":now};o["result"]={"authenticated":True,"two_factor_used":need}
 elif k in {"download","enqueue","logout"}:
  uid=a.get("user_id");sess=o["sessions"].get(uid);now=int(a.get("now",0))
  if not sess or now-int(sess["last_active"])>1800:return _e(o,"session_expired")
  sess["last_active"]=now
  if k=="download":
   raise NotImplementedError("Persist an assigned bundle through OfflineStore")
  elif k=="enqueue":
   qid=str(a.get("action_id","")).strip();kind=a.get("action_kind")
   if not qid or kind not in {"save","email","upload"}:return _e(o,"queue_denied")
   if not any(x["action_id"]==qid for x in o["queue"]):o["queue"].append({"action_id":qid,"user_id":uid,"kind":kind,"payload":deepcopy(a.get("payload")),"status":"pending"})
   o["result"]={"queued":qid}
  else:raise NotImplementedError("Remove persisted user bundles before logout")
 elif k=="set_connection":o["online"]=bool(a.get("online"));o["result"]={"online":o["online"]}
 elif k=="flush":raise NotImplementedError("Synchronize through an authenticated session and transport")
 elif k=="status":o["result"]={"online":o["online"],"last_up":o["last_up"],"last_down":o["last_down"],"pending":sum(x["status"]=="pending" for x in o["queue"])}
 else:return _e(o,"unknown_action")
 o.pop("error",None);return o
