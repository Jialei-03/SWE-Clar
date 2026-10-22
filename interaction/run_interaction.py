"""Run multi-cycle interaction with isolated task state."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import time


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_patch(previous, destination):
    """Copy only model code and runtime identity, NEVER verifier artifacts."""
    if previous is None:
        return None
    source = previous / '_runtime'
    assert (source / 'task.patch').is_file(), 'Completed round missing code patch'
    target = destination / '_runtime'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('runtime.json', 'task.patch'):
        assert not (target / name).exists(), 'Cannot replace a live round snapshot'
        shutil.copy2(source / name, target / name)
    assert sha(source / 'task.patch') == sha(target / 'task.patch')
    return sha(target / 'task.patch')


def observable_coding_summary(document):
    """Explicit allowlist. Never copy an evaluator/session object as feedback."""
    actions = (document.get('branches', {}).get('coding') or {}).get('actions', [])
    return [{'summary': str(a.get('message', '')),
             'own_checks': (a.get('delivery_submission') or {}).get('checks', [])}
            for a in actions if a.get('done')]


def disclosure_schedule(slots):
    eligible = [s for s in slots if not s.private_or_non_disclosable
                and s.temporal_origin in {'preexisting_private', 'initially_public'}
                and s.prepared_answer.strip()]
    public = sorted([s for s in eligible if s.initially_visible], key=lambda s: s.slot_id)
    hidden = sorted([s for s in eligible if not s.initially_visible], key=lambda s: s.slot_id)
    return [public] + [[s] for s in hidden]


class SingleAspect:
    def __init__(self, adapter, config, path):
        self.adapter, self.config, self.path = adapter, config, path

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def __call__(self, context):
        from llm import chat, extract_json
        instruction = ('Interleaved clarification protocol: inspect the current code and '
            'approved conversation. If needed, ask about ONE concrete decision/aspect '
            'only, not a list of independent topics. After this answer you will implement '
            'before asking again. An API signature and its directly connected shape count '
            'as one aspect; unrelated workflows do not. If the current implementation is '
            'complete and you have no remaining uncertainty, finish_clarification. '
            'Before the first implementation, finish means implement without questions. '
            'Private test results and Audit answers are unavailable. Do not infer them.')
        ctx = copy.deepcopy(context)
        ctx['interaction_protocol'] = instruction
        records = []
        for attempt in range(3):
            raw = self.adapter(ctx)
            action = json.loads(raw)
            if action.get('action') == 'ready':
                return raw
            message = action.get('message', '')
            response = chat(self.config,
                'Judge ONLY whether the message asks about one concrete decision/aspect. '
                'Do not answer the question or invent project facts. Connected interface '
                'details count as one; independently answerable unrelated topics do not. '
                'Return JSON {"single_aspect": boolean, "reason": string}.',
                [{'role': 'user', 'content': message}])
            verdict = extract_json(response.text, expected_type=dict)
            records.append({'attempt': attempt, 'action': action,
                            'candidate_trace': self.adapter.last_trace,
                            'verdict': verdict, 'guard_usage': vars(response)})
            save(self.path, records)
            if verdict.get('single_aspect') is True:
                return raw
            ctx['protocol_feedback'] = ('Your previous question bundled independent '
                'aspects. Select just ONE aspect; do not ask the others in this turn.')
            ctx['previous_rejected_question'] = message
        raise RuntimeError('single_aspect_protocol_failed_after_three_attempts')


def run(args):
    import sys
    sys.path.insert(0, str(args.release / 'harness'))
    from llm import RoleConfig
    from runtime.composition import build_engine
    from runtime.delivery_contract import require_experiment_ready
    from runtime.client import render_requirement_disclosure
    from runtime.canonical import digest_json

    dataset = args.release / 'SWE-Clar'
    require_experiment_ready(dataset)
    config = json.loads(args.config.read_text())
    profile = dict(config['candidate'])
    key_env = profile.pop('api_key_env', None)
    if not key_env:
        raise ValueError('candidate.api_key_env must name your credential environment variable')
    profile['api_key'] = os.environ[key_env]
    role_configs = {r: RoleConfig.from_profile(config[r]) for r in ('client', 'supervisor', 'judge')}
    root = args.output.resolve()
    if root.is_relative_to(dataset.resolve()) or dataset.resolve().is_relative_to(root):
        raise ValueError('Output must be separate from the dataset')
    root.mkdir(parents=True, exist_ok=False)
    started = time.time()
    previous = None
    history = None
    own_summaries = []
    rounds = []
    protocol = {'name': args.mode, 'version': 'interaction400-v1',
                'task': args.task, 'hidden_test_feedback': False,
                'audit_feedback': False, 'max_coding_cycles': 12,
                'model': config['candidate']['model'], 'thinking': 'max', 'started_at': started}
    save(root / 'protocol.json', protocol)
    schedule = None
    ending = None
    try:
        for cycle in range(12):
            folder = root / f'round-{cycle:02d}'
            folder.mkdir()
            state = folder / 'state'
            engine, profiles, adapters = build_engine(args.task,
                tasks_dir=dataset / 'tasks', state_dir=state, profile=profile,
                client_config=role_configs['client'], judge_config=role_configs['judge'],
                supervisor_config=role_configs['supervisor'], audit_scoring='ru_tiered_v1')
            if schedule is None:
                schedule = disclosure_schedule(engine.registry.slots)
                save(root / 'disclosure-order.json', [[s.slot_id for s in row] for row in schedule])
                if args.mode == 'progressive_oracle':
                    assert len(schedule) <= 12, 'Set and preregister sufficient round budget before launch'
            current = engine.create_run(None, benchmark_mode='clarify', execution_mode='auto',
                                        experiment_version='interaction400-v1')
            sid = current['session_id']
            lineage = {'cycle': cycle, 'previous_round': cycle - 1 if cycle else None,
                       'protocol': args.mode, 'inner_engine_mode': 'clarify',
                       'note': 'Inner mode is a branch engine carrier, not baseline Clarify.'}
            engine._patch(sid, {'interaction_pilot': lineage})
            if history is not None:
                dialogue = copy.deepcopy(history)
                dialogue.update(pending_exchange=None, pending_actor='candidate',
                                operation_error=None, end_reason=None)
                engine._patch(sid, {'dialogue': dialogue})
            current = engine.repository.get_session(sid)
            if own_summaries:
                message = {'message_id': f'own-implementation-{cycle}', 'role': 'candidate',
                    'content': 'Your preceding implementation notes (not external test feedback):\n'
                               + json.dumps(own_summaries[-1], ensure_ascii=False),
                    'timestamp': engine._now()}
                engine._patch(sid, {'dialogue': {'messages': [*current['dialogue']['messages'], message]}})
            hashes = {}
            for suffix in ('clarification-inspect', 'audit-inspect', 'coding'):
                hashes[suffix] = seed_patch(previous, state / 'workdirs' / f'{sid}-{suffix}')
            assert len(set(hashes.values())) == 1
            save(folder / 'branch-source-lineage.json', hashes)
            if args.mode == 'interleaved_clarify':
                from review_adapter import ReviewCandidate
                engine.candidate_turn = SingleAspect(ReviewCandidate(adapters['PiCandidateTurn'], cycle), role_configs['judge'],
                                                     folder / 'question-scope-check.json')
                current = engine.step(sid)
                if current['status'] in engine.TERMINAL:
                    raise RuntimeError('Candidate failed; inspect preserved round state')
                if current['cursor'] == 'audit.agent' and engine.candidate_turn.last_decision == 'finish_task':
                    save(folder / 'decision.json', current)
                    ending = 'agent_finished'
                    engine._patch(sid, {'status': 'succeeded', 'cursor': 'completed', 'phase': 'completed', 'interaction_stop_only': True})
                    break
                if current['cursor'] == 'dialogue.client':
                    current = engine.step(sid)
                    if current['cursor'] != 'dialogue.candidate' or current['status'] in engine.TERMINAL:
                        raise RuntimeError('Client exchange failed; inspect preserved round state')
                    engine._patch(sid, {'dialogue': {'end_reason': 'interleaved_cycle_boundary',
                                                     'pending_actor': 'none'}})
                    engine._freeze(sid)
                else:
                    assert current['cursor'] == 'audit.agent', current['cursor']
            else:
                newly = schedule[cycle]
                current = engine.repository.get_session(sid)
                content = '\n\n'.join(render_requirement_disclosure(s) for s in newly)
                if content:
                    m = {'message_id': f'progressive-oracle-{cycle}', 'role': 'client',
                         'content': content, 'origin': 'progressive_oracle', 'timestamp': engine._now()}
                    engine._patch(sid, {'dialogue': {'messages': [*current['dialogue']['messages'], m]}})
                save(folder / 'revealed.json', {'ids': [s.slot_id for s in newly],
                    'payload_sha256': digest_json(content), 'full_readme_included': False})
                engine._patch(sid, {'dialogue': {'end_reason': 'progressive_oracle_cycle_boundary',
                                                 'pending_actor': 'none'}})
                engine._freeze(sid)
            current = engine.repository.get_session(sid)
            history = copy.deepcopy(current['dialogue'])
            assert current['branch_envelopes']['audit']['base_prefix_digest'] == current['branch_envelopes']['coding']['base_prefix_digest']
            save(folder / 'freeze.json', current['frozen_context'])
            while current['status'] not in engine.TERMINAL:
                save(root / 'progress.json', {'status': 'running', 'cycle': cycle,
                     'cursor': current['cursor'], 'completed_rounds': len(rounds), 'at': time.time()})
                current = engine.step(sid)
                save(folder / 'session.json', current)
                if current.get('evaluation_error') or any(s.get('status') == 'failed_retryable' for s in current.get('steps', [])):
                    raise RuntimeError('Round interruption; no blind retry')
            if current['status'] != 'succeeded':
                raise RuntimeError('Round did not complete; preserve failure rather than skip')
            previous = state / 'workdirs' / f'{sid}-coding'
            assert (previous / '_runtime/task.patch').is_file()
            own_summaries.append(observable_coding_summary(current))
            rounds.append({'cycle': cycle, 'session_id': sid, 'session': str(folder / 'session.json'),
                           'patch_sha256': sha(previous / '_runtime/task.patch'), 'at': time.time()})
            save(root / 'rounds.json', rounds)
            if args.mode == 'progressive_oracle' and cycle == len(schedule) - 1:
                ending = 'all_goals_revealed'
                break
        if ending is None:
            ending = 'cycle_budget_exhausted'
        save(root / 'result.json', {'status': 'complete' if ending != 'cycle_budget_exhausted' else 'budget_exhausted',
            'end_reason': ending, 'rounds': rounds, 'elapsed_s': time.time()-started,
            'final_result': rounds[-1]['session'] if rounds else None})
    except Exception as exc:
        save(root / 'error.json', {'type': type(exc).__name__, 'message': str(exc), 'at': time.time()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--mode', choices=['interleaved_clarify', 'progressive_oracle'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
