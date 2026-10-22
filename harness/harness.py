"""SWE-Clar headless CLI: validate a release or run one durable Pi experiment."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from runtime.registry import load_registry
from runtime.manifests import manifest_from_registry, validate_test_manifest
from runtime.task_input import build_initial_task_input
from runtime.task_runtime import load_task_runtime
from runtime.composition import build_engine
from llm import RoleConfig
from runtime.retries import advance, should_continue

def validate(dataset, require_runtime=False):
    tasks = dataset / 'tasks'
    if not tasks.is_dir():
        tasks = dataset / 'processed/tasks'
    rows = []
    for task in sorted(p for p in tasks.iterdir() if p.is_dir()):
        registry = load_registry(task)
        manifest = manifest_from_registry(registry)
        issues = [i.model_dump() for i in validate_test_manifest(manifest, registry) if i.blocking]
        if issues:
            raise ValueError({task.name: issues})
        initial = build_initial_task_input(task, registry)
        if not initial.starter_code_paths:
            raise ValueError(task.name + ': empty starter materials')
        if initial.public_test_paths or initial.visible_requirement_unit_ids:
            raise ValueError(task.name + ': pilot intake unexpectedly exposes acceptance material')
        for unit in registry.slots:
            for test in unit.tests:
                if not (task / test.file).is_file():
                    raise ValueError(task.name + ': missing ' + test.file)
        spec = load_task_runtime(task)
        if require_runtime and spec is None:
            raise ValueError(task.name + ': no runtime catalog entry')
        rows.append({'task_id': task.name, 'rus': len(registry.slots),
                     'hidden_rus': sum(not u.initially_visible for u in registry.slots),
                     'public_files': len(initial.starter_code_paths)+len(initial.public_test_paths),
                     'runtime_configured': spec is not None})
    if not rows:
        raise ValueError('No tasks')
    return {'task_count': len(rows), 'ru_count': sum(r['rus'] for r in rows), 'tasks': rows}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('validate')
    check.add_argument('--dataset', type=Path, required=True)
    check.add_argument('--runtime-catalog', type=Path)
    check.add_argument('--require-runtime', action='store_true')
    run = sub.add_parser('run')
    run.add_argument('--dataset', type=Path, required=True)
    run.add_argument('--runtime-catalog', type=Path, required=True)
    run.add_argument('--config', type=Path, required=True)
    run.add_argument('--task', required=True)
    run.add_argument('--mode', choices=['direct','clarify','oracle'], default='clarify')
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--resume', help='Existing session ID; never creates another attempt')
    run.add_argument('--retry', action='store_true', help='Explicitly retry the failed checkpoint when resuming')
    run.add_argument('--steps', type=int, help='Stop after this many checkpoints; default runs to completion')
    args = parser.parse_args()
    if args.runtime_catalog:
        os.environ['SWECLAR_RUNTIME_CATALOG'] = str(args.runtime_catalog.resolve())
    if args.command == 'validate':
        print(json.dumps(validate(args.dataset.resolve(), args.require_runtime), indent=2))
        return
    dataset=args.dataset.resolve(); state=args.output.resolve()
    from runtime.delivery_contract import require_experiment_ready
    require_experiment_ready(dataset)
    if state.is_relative_to(dataset) or dataset.is_relative_to(state):
        parser.error('Output must be separate from the dataset')
    if args.retry and not args.resume:
        parser.error('--retry requires --resume')
    if args.steps is not None and args.steps < 1:
        parser.error('--steps must be positive')
    cfg=json.loads(args.config.read_text())
    profile=dict(cfg['candidate'])
    key_env=profile.pop('api_key_env', None)
    if key_env:
        profile['api_key']=os.environ[key_env]
    tasks=dataset/'tasks'
    if not tasks.is_dir():tasks=dataset/'processed/tasks'
    engine,profiles,adapters=build_engine(args.task,tasks_dir=tasks,state_dir=state,
        profile=profile,client_config=RoleConfig.from_profile(cfg['client']),
        judge_config=RoleConfig.from_profile(cfg['judge']),
        supervisor_config=RoleConfig.from_profile(cfg['supervisor']) if 'supervisor' in cfg else None,
        audit_scoring=cfg.get('audit_scoring','legacy'))
    if args.resume:
        current=engine.repository.get_session(args.resume)
        if current['task_id']!=args.task or current['benchmark_mode']!=args.mode:
            parser.error('Resume task/mode does not match stored run')
        engine._check_run_contract(current)
        if args.retry:current=engine.retry(args.resume)
    else:
        current=engine.create_run(None if args.mode=='clarify' else 0,
            benchmark_mode=args.mode,execution_mode='auto',experiment_version=cfg.get('experiment_version','swe-clar'))
    sid=current['session_id']
    current=engine.finish_initialization(sid)
    count=0
    try:
        while should_continue(current, engine.TERMINAL) and (args.steps is None or count<args.steps):
            print(json.dumps({'session_id':sid,'cursor':current.get('cursor'),'status':current['status']}),flush=True)
            current=advance(engine,sid);count+=1
    finally:
        current=engine.repository.get_session(sid)
        (state/(sid+'.json')).write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'session_id':sid,'status':current['status'],'cursor':current.get('cursor'),
                      'result':str(state/(sid+'.json'))}),flush=True)
    if current['status']=='failed':raise SystemExit(2)

if __name__=='__main__':
    main()
