"""Provider-neutral role prompts and structured model response adapters."""

from __future__ import annotations
from uuid import uuid4

import prompts
from .online_annotations import RUAnnotation, validate_annotations

import json,re
from copy import deepcopy
from typing import Any

from llm import RoleConfig, chat, extract_json

from .audit import SEMANTIC_AUDIT_RESPONSE_SCHEMA
from .client import SupervisorReview


def _question_quote_present(quote: object, question: str) -> bool:
    """Ground quotes without rejecting typographic apostrophe/quote variants.

    No paraphrase, case-folding, punctuation deletion or semantic inference.
    The raw model quotation remains unchanged in the evidence trace.
    """
    if not isinstance(quote,str) or not quote.strip():return False
    typography=str.maketrans({'\u2018':"'",'\u2019':"'",'\u201c':'"','\u201d':'"'})
    return quote.translate(typography) in question.translate(typography)


_AUDIT_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answers"],
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ru_id", "status", "value"],
                "properties": {
                    "ru_id": {"type": "string", "minLength": 1},
                    "status": {"enum": ["known", "unknown"]},
                    "value": {},
                },
                "allOf": [
                    {
                        "if": {"properties": {"status": {"const": "unknown"}}},
                        "then": {
                            "properties": {
                                "value": {"type": "null"},
                            }
                        },
                    },
                    {
                        "if": {"properties": {"status": {"const": "known"}}},
                        "then": {
                            "properties": {
                                "value": {"not": {"type": "null"}},
                            }
                        },
                    },
                ],
            },
        }
    },
}


_MATCHER_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["matched_slot_ids", "confidence", "no_match_reason"],
    "properties": {
        "matched_slot_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "confidence": {
            "type": "object",
            "additionalProperties": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
        },
        "no_match_reason": {"type": ["string", "null"]},
    },
}


_SUPERVISOR_SCHEMA = SupervisorReview.model_json_schema()
_SUPERVISOR_SCHEMA['required'] = ['decision','violations','rewrite_instruction','reason','ru_annotations']
_SUPERVISOR_SCHEMA['properties'] = {k:v for k,v in _SUPERVISOR_SCHEMA['properties'].items() if k in _SUPERVISOR_SCHEMA['required']}

_SCOPE_AXES = ['authorization','business_outcome','input_validation','invocation_contract',
               'computation','storage_and_replay','provider_protocol','failure_handling',
               'event_triggers','presentation','conversation_management']
_SCOPE_PLAN_SCHEMA = {'type':'object','additionalProperties':False,
    'required':['requested_decisions','question_quotes','allowed_axes','unasked_details'],
    'properties':{**{k:{'type':'array','items':{'type':'string'}} for k in ('requested_decisions','question_quotes','unasked_details')},
                  'allowed_axes':{'type':'array','items':{'enum':_SCOPE_AXES}}}}


def _metadata(result) -> dict[str, Any]:
    return {
        "requested_model": result.provider_model or None,
        "provider_model": result.provider_model,
        "provider_fingerprint": result.provider_fingerprint,
        "effective_seed": result.effective_seed,
        "usage": result.usage,
        "latency_s": result.latency_s,
        "raw_stop_reason": result.raw_stop_reason,
    }


def _native_trace(
    result,
    *,
    backend: str,
    system_prompt: str,
    request_messages: list[dict[str, Any]],
    user_payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist every observable model request/response field, without secrets."""

    user_prompt = next(
        (
            str(message.get("content") or "")
            for message in reversed(request_messages)
            if message.get("role") == "user"
        ),
        json.dumps(user_payload, ensure_ascii=False),
    )
    trace = {
        "schema_version": 1,
        "trace_id": str(uuid4()),
        "backend": backend,
        "request": {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "user_payload": user_payload,
            "messages": request_messages,
            "tool_permissions": [],
        },
        "final_text": result.text,
        "final_message": result.raw_message or {},
        "messages": [
            *request_messages,
            {"role": "assistant", "content": result.text},
        ],
        "turns": [],
        "event_trace": [],
        "tool_events": [],
        "tool_call_count": 0,
        "turn_count": 1,
        "usage": result.usage,
        "latency_s": result.latency_s,
        "raw_stop_reason": result.raw_stop_reason,
    }
    private_trace=(result.raw_message or {}).get('private_tool_trace')
    if private_trace:
        trace['request']['tool_permissions']=['read']
        for key in ('messages','turns','event_trace','tool_events','tool_call_count','turn_count'):
            if key in private_trace:
                trace[key]=deepcopy(private_trace[key])
    return trace










class ClientSimulatorTransport:
    """Generate one natural Client turn without making disclosure decisions."""

    def __init__(self, config: RoleConfig, *, read_roots: list[dict[str,Any]] | None = None) -> None:
        self.config = config
        self.read_roots = deepcopy(read_roots or [])
        self.calls: list[dict[str, Any]] = []
        self.traces: list[dict[str, Any]] = []
        self.last_trace: dict[str, Any] | None = None

    def draft(self, payload: dict[str, Any]) -> object:
        system = prompts.CLIENT_SYSTEM
        contract_mode=bool(payload.get('project_context',{}).get('contract_version'))
        if payload.get('project_context',{}).get('context_protocol')=='role-context.v3-elicitation':
            system += '\nPrivate output format: return JSON with message (your complete natural reply) and interface_names: []. Nothing will be appended automatically. Include relevant interface details in your own accurate reply. If authoritative sources conflict, include contract_conflict with the private explanation; otherwise omit it or set null.'
        elif contract_mode:
            system += '\nPrivate output format: return JSON with message (the complete natural-language client reply) and interface_names (an array of exact requirement_units.name values whose delivery interfaces the current question requests). Include every requested interface; use [] only when no interface is requested. The program appends those interfaces verbatim before review. Do not invent names or include unrelated scopes. If authoritative requirements and test sources conflict, include contract_conflict with a private explanation and a nonempty placeholder message; no reply will be released. Otherwise omit contract_conflict or set it to null. This JSON envelope is not shown to the Agent.'
        wire_payload = dict(payload)
        if payload.get('project_context',{}).get('context_protocol')=='role-context.v3-elicitation':
            wire_payload['current_turn_scope_rule']=prompts.ELICITATION_SCOPE_CHECK
        messages = [{"role": "user", "content": json.dumps(wire_payload, ensure_ascii=False)}]
        result = chat(self.config, system, messages, max_retries=5,
                      **({'read_roots':self.read_roots} if self.read_roots else {}))
        self.calls.append(_metadata(result))
        self.last_trace = _native_trace(
            result,
            backend="llm-client-simulator",
            system_prompt=system,
            request_messages=messages,
            user_payload=wire_payload,
        )
        self.traces.append(self.last_trace)
        if result.raw_stop_reason not in {"stop", "end_turn"}:
            raise ValueError("Client reply must be a completed model response")
        if not result.text.strip():
            raise ValueError("Client reply must not be empty")
        if contract_mode:
            # A malformed reply is a representation error, not a failed API
            # request. Let the durable Client loop retain and repair the draft.
            return extract_json(result.text, expected_type=dict)
        return {"message": result.text}


class DisclosureSupervisorTransport:
    """Blocking disclosure guardrail and authoritative RU exposure annotator."""

    def __init__(
        self,
        config: RoleConfig,
        *, read_roots: list[dict[str,Any]] | None = None,
    ) -> None:
        self.config = config
        self.read_roots = deepcopy(read_roots or [])
        self.calls: list[dict[str, Any]] = []
        self.traces: list[dict[str, Any]] = []
        self.last_trace: dict[str, Any] | None = None
        self._scope_plans: dict[str,dict[str,Any]] = {}

    def _plan_scope(self,payload):
        request={'candidate_message':payload.get('candidate_message',''),
                 'conversation':payload.get('conversation',[]),
                 'requirement_units':deepcopy(payload.get('requirement_units',[])),
                 'project_context':deepcopy(payload.get('project_context',{})),
                 'response_schema':_SCOPE_PLAN_SCHEMA}
        key=json.dumps(request,sort_keys=True,ensure_ascii=False)
        if key in self._scope_plans:return deepcopy(self._scope_plans[key])
        messages=[{'role':'user','content':json.dumps(request,ensure_ascii=False)}]
        result=chat(self.config,prompts.SCOPE_PLANNING_SYSTEM,messages,max_retries=5)
        self.calls.append({**_metadata(result),'purpose':'independent_question_scope'})
        trace=_native_trace(result,backend='llm-disclosure-scope-plan',system_prompt=prompts.SCOPE_PLANNING_SYSTEM,request_messages=messages,user_payload=request)
        self.traces.append(trace);self.last_trace=trace
        if result.raw_stop_reason not in ('stop','end_turn'):raise ValueError('Scope planner did not complete')
        plan=extract_json(result.text,expected_type=dict)
        for name in _SCOPE_PLAN_SCHEMA['required']:
            if not isinstance(plan.get(name),list) or not all(isinstance(s,str) for s in plan[name]):raise ValueError('Malformed scope plan: '+name)
        if not plan['question_quotes'] or any(not _question_quote_present(q,request['candidate_message']) for q in plan['question_quotes']):raise ValueError('Scope plan must be grounded in the current question')
        if not plan['requested_decisions'] and set(plan['allowed_axes'])-{'conversation_management'}:raise ValueError('Factual scope requires a requested decision; unfocused conversation may have none')
        if not set(plan['allowed_axes'])<=set(_SCOPE_AXES):raise ValueError('Unknown scope-plan axis')
        self._scope_plans[key]=deepcopy(plan)
        return plan

    def review(self, payload: dict[str, Any]) -> object:
        """Decision-level review: no planner, per-sentence quotes or axis gates.

        A valid content revision is returned immediately, never rerolled for an
        approval. One bounded representation repair is allowed for invalid JSON
        or inconsistent decision fields; annotations never block the reply.
        """
        payload=deepcopy(payload)
        payload['conversation']=[{k:m[k] for k in ('role','content') if k in m}
                                 for m in payload.get('conversation',[])]
        payload['visibility_notice']={
            'private_role_context':['requirement_units','project_context.project_readme','project_context.delivery_agreement'],
            'freelancer_knowledge':'Only its initial job/allowed starter materials and approved conversation. Private README headings do not establish disclosure.'}
        schema=deepcopy(_SUPERVISOR_SCHEMA)
        schema['required']=['decision','violations','rewrite_instruction','reason']
        trace_start=len(self.traces);self.last_trace=None;error=None;previous=None
        for attempt in range(1,3):
            wire={**payload,'response_schema':schema,'review_protocol':'decision_review.v4',
                  'representation_attempt':attempt}
            if error:
                wire['representation_repair']={'validation_error':error,'previous_output':previous,
                    'instruction':'Repair JSON/decision consistency only. Preserve the substantive verdict and findings. Do not reconsider the draft to obtain approval.'}
            messages=[{'role':'user','content':json.dumps(wire,ensure_ascii=False)}]
            result=chat(self.config,prompts.SUPERVISOR_SYSTEM,messages,max_retries=5,
                        **({'read_roots':self.read_roots} if self.read_roots else {}))
            self.calls.append({**_metadata(result),'representation_attempt':attempt})
            trace=_native_trace(result,backend='llm-disclosure-supervisor-v4',
                system_prompt=prompts.SUPERVISOR_SYSTEM,request_messages=messages,user_payload=wire)
            trace['representation_attempt']=attempt;self.traces.append(trace)
            try:
                if result.raw_stop_reason not in ('stop','end_turn'):raise ValueError('Review did not finish normally')
                parsed=extract_json(result.text,expected_type=dict)
                # Accept an explicit machine code followed by its explanation.
                # Keep the original output in the durable trace; do not reinterpret
                # arbitrary prose or negated mentions as a conflict verdict.
                if isinstance(parsed.get('violations'),list):
                    parsed['violations']=[
                        'contract_conflict' if isinstance(v,str) and v.strip().startswith('contract_conflict:') else v
                        for v in parsed['violations']]
                keys=('decision','violations','rewrite_instruction','reason')
                if not set(keys)<=parsed.keys():raise ValueError('Supervisor core decision fields are required')
                review=SupervisorReview.model_validate({k:parsed[k] for k in keys})
                if review.decision=='approve':
                    try:
                        raw=parsed.get('ru_annotations')
                        if not isinstance(raw,list):raise ValueError('Optional RU annotations unavailable')
                        annotations=validate_annotations([RUAnnotation.model_validate(r) for r in raw],payload)
                        review=review.model_copy(update={'ru_annotations':annotations,
                            'disclosed_ru_ids':[r.ru_id for r in annotations if r.status=='complete'],
                            'annotation_status':'valid','annotation_errors':[]})
                    except Exception as e:
                        review=review.model_copy(update={'ru_annotations':None,'annotation_status':'unavailable','annotation_errors':[str(e)]})
                trace['annotation_status']=review.annotation_status
                self.last_trace={**trace,'semantic_attempts':deepcopy(self.traces[trace_start:])}
                return review.model_dump(mode='json')
            except Exception as e:
                error=str(e);previous=result.text;trace['validation_error']=error
                self.last_trace={**trace,'semantic_attempts':deepcopy(self.traces[trace_start:])}
        raise ValueError('Supervisor representation invalid after bounded repair: '+str(error))

    def _legacy_strict_review(self, payload: dict[str, Any]) -> object:
        system = prompts.SUPERVISOR_SYSTEM
        expected_ids = {str(unit["ru_id"]) for unit in payload.get("requirement_units", [])
                        if isinstance(unit, dict) and unit.get("ru_id")}
        # Old caller bookkeeping cannot become a new decision input.
        payload = {key: value for key, value in payload.items()
                   if key not in {"previously_disclosed_hidden_ru_ids", "triggered_ru_ids", "authorized_ru_ids", "current_client_message_id", "current_candidate_message_id"}}
        payload['conversation']=[{k:m[k] for k in ('role','content') if k in m} for m in payload.get('conversation',[])]
        self.last_trace = None
        trace_start = len(self.traces)
        elicitation=payload.get('project_context',{}).get('context_protocol')=='role-context.v3-elicitation'
        scope_plan=self._plan_scope(payload) if elicitation else None
        validation_error: str | None = None
        for semantic_attempt in range(1, 7):
            schema=deepcopy(_SUPERVISOR_SCHEMA)
            elicitation=payload.get('project_context',{}).get('context_protocol')=='role-context.v3-elicitation'
            if elicitation:
                schema['required'].append('scope_check')
                schema['properties']['scope_check']={'type':'object','additionalProperties':False,
                    'required':['question_focus','unrequested_details','segment_reviews'],'properties':{
                        'question_focus':{'type':'string','minLength':1},
                        'unrequested_details':{'type':'array','items':{'type':'string'}},
                        'segment_reviews':{'type':'array','items':{'type':'object','additionalProperties':False,
                            'required':['segment_id','classification','question_quote','necessity','axes'],
                            'properties':{'segment_id':{'type':'integer','minimum':0},
                                'classification':{'enum':['requested','indispensable','unrequested']},
                                'question_quote':{'type':'string'},'necessity':{'type':'string'},
                                'axes':{'type':'array','minItems':1,'items':{'enum':_SCOPE_AXES}}}}}}}
            wire_payload = {
                **payload,
                "response_schema": schema,
                
                "semantic_attempt": semantic_attempt,
                **(
                    {"previous_validation_error": validation_error}
                    if validation_error
                    else {}
                ),
            }
            if elicitation:
                wire_payload['precommitted_scope']=scope_plan
                wire_payload['current_turn_scope_rule']=prompts.ELICITATION_SCOPE_CHECK
                wire_payload['disclosure_segments']=[{'segment_id':i,'text':text} for i,text in enumerate(
                    part.strip() for part in re.split(r'(?<=[.!?])\s+|\n+',str(payload.get('client_draft',''))) if part.strip())]
            messages = [{
                "role": "user",
                "content": json.dumps(wire_payload, ensure_ascii=False),
            }]
            result = chat(self.config, system, messages, max_retries=5,
                          **({'read_roots':self.read_roots} if self.read_roots else {}))
            metadata = _metadata(result)
            metadata["semantic_attempt"] = semantic_attempt
            self.calls.append(metadata)
            trace = _native_trace(
                result,
                backend="llm-disclosure-supervisor",
                system_prompt=system,
                request_messages=messages,
                user_payload=wire_payload,
            )
            trace["semantic_attempt"] = semantic_attempt
            self.traces.append(trace)
            self.last_trace = {**trace, "semantic_attempts": deepcopy(self.traces[trace_start:])}
            try:
                if result.raw_stop_reason not in {"stop", "end_turn"}:
                    raise ValueError("Supervisor did not finish with an ordinary completion stop")
                parsed = extract_json(result.text, expected_type=dict)
                # Validate the decision independently; optional statistics may be unavailable.
                if not {"decision", "violations", "rewrite_instruction", "reason"} <= parsed.keys():
                    raise ValueError("Supervisor core decision fields are required")
                core={k:parsed[k] for k in ('decision','violations','rewrite_instruction','reason')}
                validated=SupervisorReview.model_validate(core)
                if elicitation:
                    scope=parsed.get('scope_check')
                    if not isinstance(scope,dict) or not isinstance(scope.get('question_focus'),str) or not scope['question_focus'].strip() or not isinstance(scope.get('unrequested_details'),list) or not all(isinstance(s,str) for s in scope['unrequested_details']):
                        raise ValueError('A complete current-question scope_check is required')
                    if validated.decision=='approve' and scope['unrequested_details']:
                        raise ValueError('Approval cannot contain unrequested disclosures; request revision instead')
                    segments=scope.get('segment_reviews')
                    if not isinstance(segments,list):raise ValueError('Segment disclosure reviews are required')
                    if validated.decision=='approve':
                        expected=list(range(len(wire_payload['disclosure_segments'])))
                        if sorted(s.get('segment_id',-1) for s in segments if isinstance(s,dict))!=expected or len(segments)!=len(expected):
                            raise ValueError('Approval must review every draft segment exactly once')
                        for segment in segments:
                            if segment.get('classification') not in ('requested','indispensable'):
                                raise ValueError('Unrequested draft segment cannot be approved')
                            quote=segment.get('question_quote')
                            if not _question_quote_present(quote,payload.get('candidate_message','')):
                                raise ValueError('Each approved disclosure needs an exact current-question quote')
                            if segment.get('classification')=='indispensable' and not str(segment.get('necessity','')).strip():
                                raise ValueError('Indispensable disclosure needs a decision-specific necessity explanation')
                            axes=segment.get('axes')
                            if not isinstance(axes,list) or not axes or not set(axes)<=set(_SCOPE_AXES):raise ValueError('Every disclosure segment needs valid axes')
                        disallowed=[s for s in segments if not set(s['axes'])<=set(scope_plan['allowed_axes'])|{'conversation_management'}]
                        if disallowed:
                            # Do not reroll an approval after the judge itself
                            # has identified facts outside the frozen question scope.
                            ids=[s['segment_id'] for s in disallowed]
                            validated=SupervisorReview(decision='revise',violations=['unrequested_disclosure_axis'],
                                rewrite_instruction='Remove the unasked clauses in disclosure segments '+str(ids)+'. Answer only the precommitted current-question decisions: '+json.dumps(scope_plan,ensure_ascii=False),
                                reason='Draft contains axes outside the independently precommitted question scope.')
                            trace['program_scope_guard']={'blocked_segment_ids':ids,'scope_plan':deepcopy(scope_plan)}
                    trace['scope_check']=deepcopy(scope)
                if validated.decision=='approve':
                    try:
                        raw=parsed.get('ru_annotations')
                        if not isinstance(raw,list):raise ValueError('Missing RU annotations')
                        annotations=validate_annotations([RUAnnotation.model_validate(r) for r in raw],payload)
                        validated=validated.model_copy(update={'ru_annotations':annotations,
                            'disclosed_ru_ids':[r.ru_id for r in annotations if r.status=='complete'],
                            'annotation_status':'valid','annotation_errors':[]})
                    except Exception as annotation_error:
                        # Statistics cannot revoke a valid reply or trigger another model call.
                        validated=validated.model_copy(update={'ru_annotations':None,
                            'annotation_status':'unavailable','annotation_errors':[str(annotation_error)]})
                trace["annotation_status"] = validated.annotation_status
                trace["annotation_errors"] = validated.annotation_errors
                self.last_trace = {**trace, "semantic_attempts": deepcopy(self.traces[trace_start:])}
                return validated.model_dump(mode="json")
            except Exception as error:
                validation_error = str(error)
                trace["validation_error"] = validation_error
                self.last_trace = {**trace, "semantic_attempts": deepcopy(self.traces[trace_start:])}
        raise ValueError(
            "Disclosure Supervisor could not produce a complete grounded review: "
            f"{validation_error}"
        )




class SemanticAuditJudge:
    """Fixed content-only judge for a Coding Agent's verbal Audit answers."""

    def __init__(self, config: RoleConfig) -> None:
        self.config = config
        self.calls: list[dict[str, Any]] = []
        self.last_response_text: str | None = None
        self.last_parsed: object | None = None
        self.last_trace: dict[str, Any] | None = None

    def __call__(self, payload: dict[str, Any]) -> object:
        system = prompts.AUDIT_JUDGE_SYSTEM
        document = dict(payload)
        document["response_schema"] = SEMANTIC_AUDIT_RESPONSE_SCHEMA
        result = chat(
            self.config,
            system,
            [{"role": "user", "content": json.dumps(document, ensure_ascii=False)}],
            max_retries=5,
        )
        if result.raw_stop_reason not in {'stop','end_turn'}:
            raise ValueError('Audit judge response did not finish normally')
        self.calls.append(_metadata(result))
        self.last_response_text = result.text
        self.last_trace = {
            "schema_version": 1,
            "trace_id": str(uuid4()),
            "backend": "fixed-semantic-judge",
            "request": {
                "system_prompt": system,
                "user_prompt": json.dumps(document, ensure_ascii=False),
                "user_payload": document,
                "tool_permissions": [],
            },
            "final_text": result.text,
            "final_message": result.raw_message or {},
            "messages": [
                {"role": "user", "content": json.dumps(document, ensure_ascii=False)},
                {"role": "assistant", "content": result.text},
            ],
            "turns": [],
            "event_trace": [],
            "tool_events": [],
            "tool_call_count": 0,
            "turn_count": 1,
            "usage": result.usage,
            "latency_s": result.latency_s,
        "raw_stop_reason": result.raw_stop_reason,
        }
        # Persist the raw judge trace before parsing. Invalid JSON is itself
        # benchmark infrastructure evidence and must remain inspectable when
        # the Step Engine retries only this fixed judge checkpoint.
        self.last_parsed = extract_json(result.text)
        return self.last_parsed


def adapter_metadata(*adapters: object) -> dict[str, Any]:
    return {
        adapter.__class__.__name__: list(getattr(adapter, "calls", []))
        for adapter in adapters
    }
