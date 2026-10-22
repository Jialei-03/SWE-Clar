"""Configured judge, historical ordinal RU scoring; never exposed to the answerer."""
from __future__ import annotations
import ast,json,hashlib
from pathlib import Path
from llm import extract_json

SYSTEM='''Evaluate the candidate's Audit answers, not its implementation. Use each RU's required behavior and agreed interface as authority; corresponding tests clarify executable meaning and coverage but must not add undeclared requirements. Do not infer any code-test outcome. Search the ENTIRE candidate answer set, regardless of which RU contains relevant evidence. Accept equivalent wording. Do not demand repeated wording or citations; do not infer omitted details from generic claims such as "follow requirements".
Score only target_ru_id using: correct = all material behavior demonstrated; partial = core behavior correct with limited missing conditions/details and no explicit contradiction; omitted = insufficient substantive answer or unknown; contradiction = explicitly incompatible behavior, including unresolved conflicting claims. Missing details are not contradictions. Read qualifiers and grammatical scope carefully: a condition applying to malformed inputs does not automatically apply to all inputs. Clearly corrected/retracted claims are not unresolved contradictions.
Scores are fixed: correct 1, partial 0.5, omitted 0, contradiction 0. Use this simple RU-level rubric, not a new fact inventory. Briefly explain material omissions or contradictions. Evidence excerpts aid review, but quotation punctuation is not a scoring condition. Return JSON only: {"ru_id":"target RU","label":"correct|partial|omitted|contradiction","reason":"brief explanation","evidence":[{"answer_ru_id":"RU-001","quote":"short excerpt"}]}'''
LABELS={'correct':1.,'partial':.5,'omitted':0.,'contradiction':0.}

def validate_request_settings(settings, profile):
    """Validate the configured SDK effort, without assuming a provider's wire schema."""
    levels=['off','minimal','low','medium','high','xhigh']
    mapping=profile.get('thinking_level_map') or {}
    supported=[v for v in levels if mapping.get(v, True) is not None and (v!='xhigh' or v in mapping)]
    expected=supported[-1] if profile.get('reasoning',True) else 'off'
    if expected=='off' or not settings:
        raise ValueError('Tiered judge requires recorded reasoning settings')
    for setting in settings:
        if setting.get('model')!=profile['model']:
            raise ValueError('Judge model mismatch')
        # Old records used the Responses-specific field; retain their validation.
        if 'thinking_level' not in setting:
            if (setting.get('reasoning') or {}).get('effort')!='max':
                raise ValueError('Judge reasoning mismatch')
        elif setting['thinking_level']!=expected or setting.get('api')!=profile.get('api','openai-completions'):
            raise ValueError('Judge SDK/API configuration mismatch')

def validated_verdict(raw, slot_id, answer_ids):
    parsed=extract_json(raw['final_text'],expected_type=dict)
    if parsed.get('ru_id')!=slot_id or parsed.get('label') not in LABELS or not isinstance(parsed.get('reason'),str) or not parsed['reason'].strip():raise ValueError('Invalid tiered Audit verdict')
    evidence=parsed.get('evidence') or []
    if not isinstance(evidence,list) or any(not isinstance(e,dict) or not isinstance(e.get('answer_ru_id'),str) or e['answer_ru_id'] not in answer_ids or not isinstance(e.get('quote'),str) for e in evidence):raise ValueError('Invalid evidence representation')
    return parsed

def test_sources(task_root,slot):
    sources={};root=Path(task_root).resolve()
    for ref in slot.tests:
        path=(root/ref.file).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('Invalid declared test source')
        code=path.read_text()
        if path.suffix=='.py':
            nodes=ast.parse(code).body;number=int(slot.slot_id.split('-')[-1])
            names={f'ru{number}',f'ru{number:03}',f'check_{number}',f'ru_{number:03}'}
            selected=[n for n in nodes if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
            if len(selected)==1:
                # Keep shared helpers/constants/imports; omit other RU entry points.
                keep=[n for n in nodes if isinstance(n,(ast.Import,ast.ImportFrom,ast.Assign,ast.AnnAssign,ast.ClassDef)) or isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and (n is selected[0] or not (n.name.startswith(('ru','check_')) or n.name=='main'))]
                code='\n\n'.join(ast.get_source_segment(code,n) or '' for n in keep)
        sources[ref.file]=code
    return sources

class TieredAuditJudge:
    def __init__(self,config,*,task_root,registry,cache_dir):
        self.config=config;self.registry=registry;self.task_root=task_root;self.cache_dir=Path(cache_dir)
        self.calls=[];self.last_trace=None;self.last_parsed=None
        p=config.pi_profile
        if not p.get('model') or p.get('thinking')!='max':raise ValueError('Specify a judge model and max reasoning')
        if not p.get('api_key_env'):raise ValueError('Specify a credential environment variable')
        self.model=p['model']

    def __call__(self,payload):
        from .pi_adapters import _run_pi_text
        items=payload['items'];byid={r['ru_id']:r for r in items}
        answers=[{'ru_id':r['ru_id'],'status':r['candidate_status'],'value':r['candidate_answer']} for r in items]
        key=hashlib.sha256(json.dumps({'system':SYSTEM,'payload':payload,'model':self.model,'effort':'max'},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        folder=self.cache_dir/key;folder.mkdir(parents=True,exist_ok=True)
        trace={'backend':'fixed-tiered-ru-judge','prompt_version':'swe-clar.audit.ru_tiered.v1','tool_permissions':[],'chunks':[],'request_settings':[]}
        self.last_trace=trace;verdicts=[]
        for slot in self.registry.slots:
            item=byid[slot.slot_id]
            request={'target_ru_id':slot.slot_id,'audit_question':item['audit_question'],'reference_answer':item['reference_answer'],'corresponding_tests':test_sources(self.task_root,slot),'candidate_answers':answers}
            file=folder/(slot.slot_id+'.json')
            if file.exists():
                saved=json.loads(file.read_text());assert saved['request']==request;raw=saved['response']
                try:validated_verdict(raw,slot.slot_id,byid)
                except (ValueError,KeyError,TypeError):
                    index=len(list(folder.glob(slot.slot_id+'.invalid-*.json')))+1
                    bad=file.with_name(file.stem+'.invalid-'+str(index)+'-'+hashlib.sha256(file.read_bytes()).hexdigest()[:16]+'.json')
                    if not bad.exists():bad.write_bytes(file.read_bytes())
                    file.unlink()
            if not file.exists():
                # Invalid attempts remain available for audit; cap retries across restarts.
                if len(list(folder.glob(slot.slot_id+'.invalid-*.json')))>=3:raise ValueError('Tiered judge invalid-output attempt limit reached')
                raw=_run_pi_text(self.config.pi_profile,session_kind='private_review',system_prompt=SYSTEM,user_payload=request,read_roots=[],timeout_s=360)
                saved={'request':request,'system_prompt':SYSTEM,'response':raw}
                temp=file.with_suffix('.tmp');temp.write_text(json.dumps(saved,ensure_ascii=False));temp.replace(file)
            trace['chunks'].append({'ru_id':slot.slot_id,'request':request,'response':raw})
            settings=raw.get('request_settings') or []
            validate_request_settings(settings,self.config.pi_profile)
            trace['request_settings'].extend(settings)
            parsed=validated_verdict(raw,slot.slot_id,byid)
            evidence=parsed.get('evidence') or []
            verdicts.append({'ru_id':slot.slot_id,'tier_label':parsed['label'],'content_correct':parsed['label']=='correct','reason':parsed['reason'],'evidence':[{k:e[k] for k in ('answer_ru_id','quote')} for e in evidence]})
        self.last_parsed={'verdicts':verdicts};self.calls.append({'model':self.model,'thinking':'max','ru_calls':len(verdicts)})
        return self.last_parsed
