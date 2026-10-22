"""Explicit read-only review actions; implementation-ready is not task-finished."""
import json

SYSTEM = '''You are the freelancer implementing this project in an interleaved workflow.
Inspect the original job, approved Client conversation AND current code. Review the
whole requested job, not only the last answered question. Code you wrote and your
own successful checks are not evidence of the Client's intended behavior.
Distinguish confirmed requirements, unresolved material assumptions, and reasonable
implementation choices that do not require Client approval. Check delivery/interface
agreements and behavior whose intended meaning cannot be inferred from allowed facts.
Do not invent uncertainty just to prolong the conversation, or seek private tests.
Choose one explicit action:
ask_client: one focused material uncertainty needs Client clarification before the
next implementation. Ask ONE aspect, with connected interface details if necessary.
implement_next: requirements suffice for the next step, but implementation work remains.
finish_task: the requested job is implemented and no material uncertainty remains.
This is NOT permission to start coding. It ends the entire task. Available only
after at least one completed coding cycle. Never treat 'ready to implement' as finish.
Use read tools to inspect, never write or execute code during this review. Hidden
tests, Audit questions/answers and scores are not available and must not be inferred.
Return JSON only: {"decision":"ask_client|implement_next|finish_task",
"review":[{"aspect":"...","status":"confirmed|open|design_choice",
"basis":"evidence from allowed job, conversation or code; identify assumptions"}],
"implementation_remaining":true|false,"message":"focused question or empty",
"reason":"why this action is appropriate"}.'''


def validate_decision(d, completed_cycles):
    if not isinstance(d, dict) or d.get('decision') not in {'ask_client','implement_next','finish_task'}:
        raise ValueError('Invalid review decision')
    if not isinstance(d.get('implementation_remaining'), bool):
        raise ValueError('implementation_remaining must be boolean')
    if not isinstance(d.get('review'), list) or not d['review']:
        raise ValueError('A grounded job review is required')
    for item in d['review']:
        if not isinstance(item, dict) or item.get('status') not in {'confirmed','open','design_choice'}:
            raise ValueError('Invalid review item')
        if not all(isinstance(item.get(k),str) and item[k].strip() for k in ['aspect','basis']):
            raise ValueError('Missing review grounding')
    if not isinstance(d.get('reason'),str) or not d['reason'].strip():
        raise ValueError('Missing decision reason')
    if d['decision']=='ask_client' and not (isinstance(d.get('message'),str) and d['message'].strip()):
        raise ValueError('Question required')
    if d['decision']=='finish_task':
        if not completed_cycles or d['implementation_remaining'] or any(r['status']=='open' for r in d['review']):
            raise ValueError('Cannot finish before coding or with acknowledged unresolved work')
    return d


class ReviewCandidate:
    def __init__(self, original, cycle):
        self.original, self.cycle = original, cycle
        self.last_trace = None
        self.last_workflow_action = None
        self.last_decision = None

    def __call__(self, context):
        from runtime.pi_adapters import _run_pi_text, _observable_trace
        from llm import extract_json
        # Construct the read-only review input from allowed context fields.
        payload = {k:context[k] for k in ['session_id','task_id','public_task','attachments',
            'candidate_observations','messages','protocol_feedback','previous_rejected_question'] if k in context}
        payload['completed_coding_cycles'] = self.cycle
        runtime = dict(self.original.runtime_provider(context))
        try:
            result = _run_pi_text(self.original.profile, system_prompt=SYSTEM,
                user_payload=payload, read_roots=self.original.read_roots,
                runtime_context=runtime, session_kind='private_review')
        finally:
            self.original.runtime_cleanup(runtime)
        self.last_trace = _observable_trace(result, system_prompt=SYSTEM,
            user_payload=payload, tool_permissions=['read'])
        decision = validate_decision(extract_json(result.get('final_text',''),expected_type=dict), self.cycle)
        self.last_decision = decision['decision']
        self.last_trace['interaction_review'] = decision
        action = {'action':'message','message':decision['message']} if self.last_decision=='ask_client' else {
            'action':'ready','decision_summary':decision['reason'][:500]}
        self.last_workflow_action = {'action':self.last_decision,'reason':decision['reason']}
        return json.dumps(action)
