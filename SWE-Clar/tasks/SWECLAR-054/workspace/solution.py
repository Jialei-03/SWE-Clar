from copy import deepcopy
def err(s,c): o=deepcopy(s); o["error"]={"code":c}; return o
def process_presave_action(state: dict, action: dict, service=None) -> dict:
 o=deepcopy(state) if isinstance(state,dict) else {}; a=deepcopy(action) if isinstance(action,dict) else {}; k=a.get("type")
 for n,d in (("artists",{}),("listeners",{}),("releases",{}),("campaigns",{}),("presaves",{}),("libraries",{})): o.setdefault(n,d)
 if k=="create_artist":
  aid=str(a.get("artist_id","")).strip()
  if not aid or aid in o["artists"]: return err(o,"invalid_artist")
  o["artists"][aid]={"name":a.get("name")}; o["result"]={"artist_id":aid}
 elif k=="create_release":
  rid=str(a.get("release_id","")).strip(); aid=a.get("artist_id"); ts=a.get("release_at"); uri=str(a.get("spotify_uri","")).strip()
  if not rid or rid in o["releases"] or aid not in o["artists"] or not isinstance(ts,(int,float)) or ts<=a.get("now",0) or not uri.startswith("spotify:track:"): return err(o,"invalid_release")
  o["releases"][rid]={"artist_id":aid,"release_at":ts,"spotify_uri":uri}; o["result"]={"release_id":rid}
 elif k=="publish_campaign":
  slug=str(a.get("slug","")).strip(); rid=a.get("release_id")
  release_has_campaign=any(c.get("release_id")==rid for c in o["campaigns"].values())
  if not slug or slug in o["campaigns"] or rid not in o["releases"] or release_has_campaign: return err(o,"invalid_campaign")
  o["campaigns"][slug]={"release_id":rid}; o["result"]={"slug":slug}
 elif k=="authorize_listener":
  raise NotImplementedError("Exchange the authorization code and validate the provider grant")
 elif k=="presave":
  lid=a.get("listener_id"); slug=a.get("slug"); key=f"{slug}:{lid}"
  if lid not in o["listeners"] or slug not in o["campaigns"] or a.get("consent") is not True: return err(o,"presave_denied")
  o["presaves"].setdefault(key,{"slug":slug,"listener_id":lid,"consent":True,"fulfilled":False}); o["result"]=deepcopy(o["presaves"][key])
 elif k=="fulfill":
  raise NotImplementedError("Save through the service before marking a presave fulfilled")
 else: return err(o,"unknown_action")
 o.pop("error",None); return o
