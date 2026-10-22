from copy import deepcopy
from conftest import load_solution


def ledger_rows(state):
 ledger=state["server_ledger"]
 if isinstance(ledger,dict):
  nested=ledger.get("events")
  ledger=nested if isinstance(nested,list) else list(ledger.values())
 assert isinstance(ledger,list)
 assert all(isinstance(row,dict) and isinstance(row.get("event_id"),str) for row in ledger)
 return ledger


def setup(m):
 s=m.process_cashless_action({}, {"type":"register_terminal","imei":"T","name":"one"}); s=m.process_cashless_action(s,{"type":"create_customer","customer_id":"U","name":"A"}); return m.process_cashless_action(s,{"type":"activate_card","card_id":"C","customer_id":"U"})
def test_ru_001_non_mutation():
    m = load_solution()
    m.process_cashless_action = _assert_result_contract(m.process_cashless_action)
    s = {}
    a = {'type': 'report'}
    sb = deepcopy(s)
    ab = deepcopy(a)
    m.process_cashless_action(s, a)
    assert s == sb and a == ab
def test_ru_002_entities_unique():
 m=load_solution(); s=setup(m); assert s["cards"]["C"]["balance"]==0; before=deepcopy(s); rejected=m.process_cashless_action(s,{"type":"activate_card","card_id":"C","customer_id":"U"}); assert s==before and isinstance(rejected.get("error",{}).get("code"),str) and rejected["error"]["code"]
def test_ru_003_money_and_refund_once():
 m=load_solution(); s=setup(m); s=m.process_cashless_action(s,{"type":"topup","card_id":"C","terminal_imei":"T","event_id":"e1","amount":20,"payment_method":"cash"}); s=m.process_cashless_action(s,{"type":"sale","card_id":"C","terminal_imei":"T","event_id":"e2","amount":7,"product":"food","timestamp":3}); s=m.process_cashless_action(s,{"type":"refund","card_id":"C","terminal_imei":"T","event_id":"e3","sale_event_id":"e2","amount":7,"payment_method":"card"}); assert s["cards"]["C"]["balance"]==20; before=deepcopy(s); rejected=m.process_cashless_action(s,{"type":"refund","card_id":"C","terminal_imei":"T","event_id":"e4","sale_event_id":"e2","amount":7,"payment_method":"cash"}); assert s==before and isinstance(rejected.get("error",{}).get("code"),str) and rejected["error"]["code"]
def test_ru_004_sync_exactly_once():
 m=load_solution(); s=setup(m); s=m.process_cashless_action(s,{"type":"topup","card_id":"C","terminal_imei":"T","event_id":"e1","amount":10,"payment_method":"cash"}); s=m.process_cashless_action(s,{"type":"sync","terminal_imei":"T"},upload_events=lambda rows:{"accepted_ids":[r["event_id"] for r in rows]}); assert not s["pending"]["T"]; ledger_ids=[row["event_id"] for row in ledger_rows(s)]; assert ledger_ids.count("e1")==1; r=m.process_cashless_action(s,{"type":"sync","terminal_imei":"T"},upload_events=lambda rows:{"accepted_ids":[r["event_id"] for r in rows]}); assert not r["pending"]["T"] and [row["event_id"] for row in ledger_rows(r)]==ledger_ids
def test_ru_005_reports_synced_only():
 m=load_solution(); synchronized=[{"event_id":"e1","kind":"topup","amount":20,"payment_method":"cash","terminal_imei":"T","timestamp":1},{"event_id":"e2","kind":"sale","amount":7,"product":"food","terminal_imei":"T","timestamp":3},{"event_id":"e3","kind":"refund","amount":7,"payment_method":"card","terminal_imei":"T","timestamp":4}]; pending={"T":[{"event_id":"unsynced","kind":"topup","amount":999,"payment_method":"cash","terminal_imei":"T","timestamp":5}]}; report=m.process_cashless_action({"server_ledger":synchronized,"pending":pending},{"type":"report"})["result"]
 assert report["credit_purchased"]==20 and report["total_sales"]==7
 assert report["refunds_by_payment_method"]=={"cash":0,"card":7}
 assert report["product_sales"]==[{"product":"food","terminal_imei":"T","timestamp":3,"amount":7}]


def _assert_result_contract(function):
    """Verify the declared JSON-object entry contract on the RU-001 calls."""
    from copy import deepcopy
    import json

    def checked(*args, **kwargs):
        before = deepcopy((args, kwargs))
        result = function(*args, **kwargs)
        assert isinstance(result, dict), "entry point must return a JSON object"
        assert (args, kwargs) == before, "entry point mutated its inputs"
        json.dumps(result, allow_nan=False)
        replay = function(*deepcopy(args), **deepcopy(kwargs))
        assert result == replay, "entry point must be deterministic"
        return result

    return checked
