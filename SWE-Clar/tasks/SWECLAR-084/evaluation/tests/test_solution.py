from copy import deepcopy
from math import inf, nan

from candidate_proxy import call,cli
from types import SimpleNamespace
def load_solution():return SimpleNamespace(process_coaching_action=call)


def base():
    return {"users": {"c": {"role": "coach"}, "a": {"role": "athlete"}, "x": {"role": "athlete"}}, "credits": {"a": 1}}


def service(module):
    return module.process_coaching_action(base(), {"type": "publish_service", "coach_id": "c", "service_id": "s", "specialty": "Strength", "modality": "hybrid", "price": 10, "slots": ["t", " t ", "u"]})


def booked(module):
    return module.process_coaching_action(service(module), {"type": "book", "athlete_id": "a", "service_id": "s", "session_id": "b", "slot": "t", "purchase_type": "subscription"})


def test_ru_001_is_deterministic_and_immutable_for_both_inputs():
    module = load_solution(); state = base()
    action = {"type": "publish_service", "coach_id": "c", "service_id": "s", "specialty": "Strength", "modality": "hybrid", "price": 10, "slots": ["t"]}
    before_state, before_action = deepcopy(state), deepcopy(action)
    assert module.process_coaching_action(state, action) == module.process_coaching_action(state, action)
    assert state == before_state and action == before_action
    malformed = base(); malformed["services"] = []
    assert module.process_coaching_action(malformed, action)["error"]["code"]
    assert module.process_coaching_action({}, None)["error"]["code"]


def test_ru_002_service_publication_and_discovery_are_strict_and_stable():
    module = load_solution(); state = service(module)
    assert state["services"]["s"]["slots"] == ["t", "u"]
    state = module.process_coaching_action(state, {"type": "publish_service", "coach_id": "c", "service_id": "a", "specialty": " strength basics ", "modality": "online", "price": 0, "slots": ["v"]})
    found = module.process_coaching_action(state, {"type": "discover", "specialty": "STRENGTH"})
    assert [row["service_id"] for row in found["result"]["services"]] == ["s", "a"]
    invalid = [
        {"coach_id": "a", "price": 1, "slots": ["t"]},
        {"coach_id": "c", "price": True, "slots": ["t"]},
        {"coach_id": "c", "price": nan, "slots": ["t"]},
        {"coach_id": "c", "price": inf, "slots": ["t"]},
        {"coach_id": "c", "price": -1, "slots": ["t"]},
        {"coach_id": "c", "price": 1, "slots": []},
        {"coach_id": "c", "price": 1, "slots": [None]},
    ]
    for index, patch in enumerate(invalid):
        request = {"type": "publish_service", "coach_id": "c", "service_id": f"bad{index}", "specialty": "x", "modality": "online", "price": 1, "slots": ["t"], **patch}
        assert module.process_coaching_action(base(), request)["error"]["code"]
    assert module.process_coaching_action(state, {"type": "discover", "modality": "telepathy"})["error"]["code"]


def test_ru_003_booking_prevents_conflicts_and_debits_integer_credit_once():
    module = load_solution(); state = booked(module)
    assert state["credits"]["a"] == 0 and state["sessions"]["b"]["status"] == "booked"
    replay = module.process_coaching_action(state, {"type": "book", "athlete_id": "a", "service_id": "s", "session_id": "b", "slot": "t", "purchase_type": "subscription"})
    assert replay["error"]["code"] and replay["credits"]["a"] == 0
    occupied = module.process_coaching_action(state, {"type": "book", "athlete_id": "x", "service_id": "s", "session_id": "b2", "slot": "t", "purchase_type": "one_time"})
    assert occupied["error"]["code"]
    for credit in (True, "1", 1.0, 0, -1):
        candidate = service(module); candidate["credits"]["a"] = credit
        result = module.process_coaching_action(candidate, {"type": "book", "athlete_id": "a", "service_id": "s", "session_id": "z", "slot": "u", "purchase_type": "subscription"})
        assert result["error"]["code"]


def test_ru_004_plans_require_a_live_relationship_and_one_checkin_per_week():
    module = load_solution(); state = booked(module)
    assign = {"type": "assign_plan", "coach_id": "c", "athlete_id": "a", "plan_id": "p", "plan_type": "training", "content": {"sets": 3}}
    state = module.process_coaching_action(state, assign)
    assert state["plans"]["p"]["content"] == {"sets": 3}
    assert module.process_coaching_action(state, assign)["error"]["code"]
    checkin = {"type": "checkin", "plan_id": "p", "athlete_id": "a", "week": " 2026-W01 ", "content": "done"}
    state = module.process_coaching_action(state, checkin)
    assert state["checkins"][0]["week"] == "2026-W01"
    assert module.process_coaching_action(state, {**checkin, "week": "2026-W01"})["error"]["code"]
    cancelled = booked(module); cancelled["sessions"]["b"]["status"] = "cancelled"
    assert module.process_coaching_action(cancelled, assign)["error"]["code"]
    assert module.process_coaching_action(state, {**checkin, "week": None})["error"]["code"]


def test_ru_005_reviews_and_messages_enforce_lifecycle_participants_and_replays():
    module = load_solution(); state = booked(module)
    review = {"type": "review", "session_id": "b", "athlete_id": "a", "review_id": "r", "rating": 5}
    assert module.process_coaching_action(state, review)["error"]["code"]
    state = module.process_coaching_action(state, {"type": "complete_session", "session_id": "b", "coach_id": "c"})
    state = module.process_coaching_action(state, review)
    assert len(state["reviews"])==1 and all(state["reviews"][0][k]==v for k,v in {"review_id":"r","session_id":"b","rating":5}.items())
    for rating in (True, 0, 6, 4.5):
        fresh = module.process_coaching_action(booked(module), {"type": "complete_session", "session_id": "b", "coach_id": "c"})
        assert module.process_coaching_action(fresh, {**review, "review_id": f"r{rating}", "rating": rating})["error"]["code"]
    message = {"type": "message", "session_id": "b", "message_id": "m", "sender_id": "a", "recipient_id": "c", "text": " hello "}
    state = module.process_coaching_action(state, message)
    replay = module.process_coaching_action(state, message)
    assert replay["result"]["duplicate"] is True and len(replay["messages"]) == 1
    conflict = module.process_coaching_action(state, {**message, "text": "different"})
    assert conflict["error"]["code"]
    outsider = module.process_coaching_action(state, {**message, "message_id": "x", "sender_id": "x"})
    assert outsider["error"]["code"]


def test_ru_001_actual_sqlite_and_public_envelope():
 a={"type":"publish_service","coach_id":"c","service_id":"s","specialty":"Strength","modality":"hybrid","price":10,"slots":["t"]}
 rows=cli(base(),[{'command':'act','value':a},{'command':'show'},{'command':'act','value':{**a,'coach_id':'a','service_id':'bad'}},{'command':'show'},{'command':'init','value':{}}])
 assert all(row['returncode']==0 for row in rows)
 assert rows[1]['output']['result']['service_id']=='s' and 'services' not in rows[1]['output']
 assert rows[2]['output']['services']['s']['price']==10 and rows[3]['output'].get('error') and rows[4]['output']==rows[2]['output'] and rows[5]['output'].get('error')

def test_ru_003_credit_free_one_time_and_client_price_ignored():
 s=service(load_solution());request={'type':'book','athlete_id':'a','service_id':'s','session_id':'b','slot':'t','purchase_type':'one_time','price':0,'credits':999}
 s=call(s,request);assert s['credits']['a']==1 and s['sessions']['b']['price']==10
 bad=call(s,{**request,'session_id':'another','purchase_type':'subscription'});assert bad.get('error') and bad['credits']==s['credits']

def test_ru_004_participants_and_plan_variants():
 s=booked(load_solution())
 for kind in ['training','meal','supplement']:
  s=call(s,{'type':'assign_plan','coach_id':'c','athlete_id':'a','plan_id':kind,'plan_type':kind,'content':{'label':'Synthetic reference'}})
 assert call(s,{'type':'checkin','athlete_id':'x','plan_id':'training','week':'2026-W01','content':'done'}).get('error')
 assert call(s,{'type':'assign_plan','coach_id':'c','athlete_id':'x','plan_id':'denied','plan_type':'training','content':'x'}).get('error')

def test_ru_005_history_is_only_for_participants():
 s=booked(load_solution());a={'type':'message','session_id':'b','message_id':'m','sender_id':'a','recipient_id':'c','text':' Hello '};s=call(s,a)
 s=call(s,{'type':'book','athlete_id':'x','service_id':'s','session_id':'other','slot':'u','purchase_type':'one_time'})
 s=call(s,{**a,'session_id':'other','message_id':'other-message','sender_id':'x','text':'Other conversation'})
 for sid,athlete,rating in [('b','a',5),('other','x',2)]:
  s=call(s,{'type':'complete_session','coach_id':'c','session_id':sid})
  s=call(s,{'type':'review','athlete_id':athlete,'session_id':sid,'review_id':'review-'+sid,'rating':rating})
 for sid,athlete,text,rating,mid in [('b','a','Hello',5,'m'),('other','x','Other conversation',2,'other-message')]:
  for actor in [athlete,'c']:
   view=call(s,{'type':'view_session','actor_id':actor,'session_id':sid})['result']
   assert len(view['messages'])==1 and all(view['messages'][0].get(k)==v for k,v in {'message_id':mid,'session_id':sid,'sender_id':athlete,'recipient_id':'c','text':text}.items())
   assert len(view['reviews'])==1 and all(view['reviews'][0].get(k)==v for k,v in {'review_id':'review-'+sid,'session_id':sid,'rating':rating}.items())
 assert call(s,{'type':'view_session','actor_id':'a','session_id':'other'}).get('error')
 assert call(s,{'type':'view_session','actor_id':'x','session_id':'b'}).get('error')
 assert call(s,{**a,'message_id':'self','recipient_id':'a'}).get('error')
