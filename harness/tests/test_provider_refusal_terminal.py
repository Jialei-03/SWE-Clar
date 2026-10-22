from runtime.step_engine import StepEngine

def test_provider_refusal_is_terminal_even_if_caller_requests_retry():
    document={'revision':0,'cursor':'dialogue.candidate','steps':[{'step_id':'s'}],'errors':[]}
    class Repository:
        def get_session(self, _):return document
        def compare_and_swap(self, session_id, revision, patch):document.update(patch);return document
    engine=object.__new__(StepEngine);engine.repository=Repository()
    engine._now=lambda:'2026-09-20T00:00:00+00:00'
    error=RuntimeError('provider_refusal category=reasoning_extraction');error.provider_refusal=True
    engine._fail_step('r','s','candidate.action_failed',error,retryable=True)
    assert document['status']=='failed'
    assert document['errors'][-1]['code']=='provider.refusal'
    assert document['errors'][-1]['retryable'] is False
