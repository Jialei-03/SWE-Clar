import json
from pathlib import Path
import pytest
from runtime.audit import AuditAnswer, SemanticAuditVerdict, validate_audit_output, build_semantic_judge_payload
from runtime.registry import load_registry

@pytest.mark.parametrize('key',['ru_id','slot_id'])
def test_audit_identifiers_canonicalize_without_changing_content(key):
 a=AuditAnswer.model_validate({key:'RU-001','status':'known','value':'answer'})
 assert a.slot_id==a.ru_id=='RU-001'
 assert a.model_dump()['ru_id']=='RU-001' and 'slot_id' not in a.model_dump()
 v=SemanticAuditVerdict.model_validate({key:'RU-001','content_correct':True,'reason':'Equivalent'})
 assert v.slot_id=='RU-001' and 'slot_id' not in v.model_dump()

def test_new_answers_reach_judge_with_same_ru_set():
 reg=load_registry(Path(__file__).resolve().parents[2]/'SWE-Clar/tasks/SWECLAR-013')
 raw={'answers':[{'ru_id':u.ru_id,'status':'known','value':'answer'} for u in reg.slots]}
 out=validate_audit_output(raw,reg)
 payload=build_semantic_judge_payload(out,reg)
 assert [x['ru_id'] for x in payload['items']]==[u.ru_id for u in reg.slots]
 assert 'slot_id' not in json.dumps(payload)
 with pytest.raises(ValueError):validate_audit_output({'answers':[raw['answers'][0]]*len(reg.slots)},reg)
