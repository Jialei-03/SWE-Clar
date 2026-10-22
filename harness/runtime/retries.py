"""Durable checkpoint retries. Never retry a completed but low-scoring delivery."""
MAX_RETRIES = 5

def pending_error(run):
    for e in [run.get('evaluation_error'),(run.get('dialogue') or {}).get('operation_error')]:
        if e:
            return e
    failed=next((s for s in reversed(run.get('steps',[])) if s.get('status')=='failed_retryable'),None)
    return failed.get('error') if failed else None

def advance(engine, session_id):
    current=engine.repository.get_session(session_id)
    error=pending_error(current)
    if not error:
        return engine.step(session_id)
    # Keep a stable counter through changing error messages and model step IDs.
    successful=sum(s.get('status')=='succeeded' for s in current.get('steps',[]))
    key=f"{current.get('cursor')}:{successful}"
    retries=dict(current.get('automatic_retries') or {})
    used=retries.get(key,0)
    if used>=MAX_RETRIES:
        engine._patch(session_id,{'status':'failed','runner_error':{'code':'retry_exhausted','checkpoint':key,'retries':used,'cause':error}})
        return engine.repository.get_session(session_id)
    retries[key]=used+1
    engine._patch(session_id,{'automatic_retries':retries})
    return engine.retry(session_id)


def should_continue(run, terminal_statuses):
    """Incomplete infrastructure evaluation is retryable without recoding."""
    if run.get('status') not in terminal_statuses:
        return True
    error=run.get('evaluation_error') or {}
    return run.get('status')=='incomplete' and error.get('retryable') is True
