"""Run a durable, explicitly scoped task x mode cohort without a frontend."""
from pathlib import Path
import argparse, concurrent.futures, json, os, sqlite3, subprocess, sys, time, threading
from runtime.run_contract import file_inventory
from runtime.canonical import digest_bytes, digest_json


def atomic_json(path, document):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(document,ensure_ascii=False,indent=2));temp.replace(path)


def input_signature(dataset, config, catalog):
    # Protect terminal-cell reuse too: it does not invoke harness.py's resume
    # contract. Secrets are never persisted; only content digests are saved.
    root=Path(__file__).resolve().parent
    files=[*root.glob('*.py'),*root.joinpath('runtime').glob('*.py'),*root.joinpath('pi').glob('*.mjs')]
    files += [root/name for name in ['requirements.txt','pi/package.json','pi/package-lock.json'] if (root/name).is_file()]
    code={str(p.relative_to(root)):digest_bytes(p.read_bytes()) for p in files}
    return {'code':digest_json(code),'dataset':digest_json(file_inventory(dataset)),
            'config':digest_bytes(config.read_bytes()),
            'catalog':digest_bytes(catalog.read_bytes())}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset',type=Path,required=True)
    ap.add_argument('--runtime-catalog',type=Path,required=True)
    ap.add_argument('--config',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--workers',type=int,default=8)
    ap.add_argument('--predecessors-file',type=Path,help='Prior revision workers that share the concurrency budget')
    ap.add_argument('--tasks',nargs='*')
    ap.add_argument('--cells-file',type=Path,help='Explicit task/mode cells for a documented continuation')
    ap.add_argument('--modes',nargs='+',choices=['direct','clarify','oracle'],default=['direct','clarify','oracle'])
    args=ap.parse_args()
    if args.workers<1:ap.error('--workers must be positive')
    dataset=args.dataset.resolve();root=args.output.resolve()
    from runtime.delivery_contract import require_experiment_ready
    require_experiment_ready(dataset)
    if root.is_relative_to(dataset):ap.error('Results must be outside dataset')
    root.mkdir(parents=True,exist_ok=True)
    # An OS lock prevents two batch owners racing to create the same sessions.
    import fcntl
    lock=(root/'batch.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    tasks=sorted(p.name for p in (dataset/'tasks').iterdir() if p.is_dir())
    if args.tasks:
        unknown=set(args.tasks)-set(tasks)
        if unknown:ap.error(f'Unknown tasks: {sorted(unknown)}')
        tasks=[t for t in tasks if t in args.tasks]
    config=json.loads(args.config.read_text())
    cells=[{'task_id':task,'mode':mode} for task in tasks for mode in args.modes]
    if args.cells_file:
        selected=json.loads(args.cells_file.read_text())
        valid={(c['task_id'],c['mode']) for c in cells}
        keys=[(c['task_id'],c['mode']) for c in selected]
        if not keys or len(keys)!=len(set(keys)) or not set(keys)<=valid:
            ap.error('Invalid or duplicate continuation cells')
        cells=[{'task_id':t,'mode':m} for t,m in keys]
    signature=input_signature(dataset,args.config,args.runtime_catalog)
    cohort={'input_signature':signature,'experiment_version':config['experiment_version'],'cells':cells,'workers':args.workers,
            'dataset':str(dataset),'started_at':time.time(),'results':[]}
    manifest=root/'batch.json'
    if manifest.exists():
        previous=json.loads(manifest.read_text())
        if previous.get('input_signature')!=signature or previous['cells']!=cells or previous['experiment_version']!=cohort['experiment_version']:
            ap.error('Existing cohort differs; use a separate output')
        cohort['started_at']=previous['started_at']
    atomic_json(manifest,cohort)

    def run(cell):
        if input_signature(dataset,args.config,args.runtime_catalog)!=signature:
            raise RuntimeError("Cohort inputs changed during execution; restore the frozen inputs")
        directory=root/(cell['task_id']+'-'+cell['mode']);directory.mkdir(exist_ok=True)
        state=directory/'state';db=state/'sessions.sqlite3'
        command=[sys.executable,'-B',str(Path(__file__).with_name('harness.py')),'run',
                 '--dataset',str(dataset),'--runtime-catalog',str(args.runtime_catalog.resolve()),
                 '--config',str(args.config.resolve()),'--task',cell['task_id'],'--mode',cell['mode'],
                 '--output',str(state)]
        if db.exists():
            with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as conn:rows=conn.execute('select session_id,document_json from sessions').fetchall()
            if len(rows)!=1:raise RuntimeError(f'{directory.name}: expected one durable session, got {len(rows)}')
            sid,raw=rows[0];document=json.loads(raw)
            if document['status'] in ('succeeded','incomplete','failed'):
                result={**cell,'session_id':sid,'status':document['status'],'reused_existing':True}
                atomic_json(directory/'cell.json',result);return result
            # A still-running step must be investigated, never blindly duplicated.
            if any(s.get('status')=='running' for s in document.get('steps',[])):
                raise RuntimeError(f'{directory.name}: unresolved running checkpoint; inspect its process before recovery')
            command.extend(['--resume',sid])
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        with (directory/'run.log').open('a') as log:
            proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env)
            atomic_json(directory/'process.json',{'pid':proc.pid,'started_at':time.time()})
            rc=proc.wait()
        if not db.exists():
            result={**cell,'status':'launch_failed','exit_code':rc}
        else:
            with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as conn:rows=conn.execute('select session_id,document_json from sessions').fetchall()
            if len(rows)!=1:raise RuntimeError('Expected one session per cell')
            sid,raw=rows[0];document=json.loads(raw)
            result={**cell,'session_id':sid,'status':document['status'],'exit_code':rc}
        atomic_json(directory/'cell.json',result);return result

    predecessors=json.loads(args.predecessors_file.read_text()) if args.predecessors_file else []
    admission=threading.Lock()
    active=0
    def prior_alive(item):
        try:
            raw=Path(f"/proc/{item['pid']}/stat").read_text()
            fields=raw[raw.rfind(')')+2:].split()
            return fields[19]==item['start_ticks'] and fields[0]!='Z'
        except FileNotFoundError:
            return False
    def admitted_run(cell):
        nonlocal active
        while True:
            with admission:
                if active+sum(prior_alive(p) for p in predecessors)<args.workers:
                    active+=1
                    break
            time.sleep(2)
        try:
            return run(cell)
        finally:
            with admission:active-=1

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(admitted_run,c):c for c in cells}
        for future in concurrent.futures.as_completed(futures):
            try:result=future.result()
            except Exception as exc:result={**futures[future],'status':'runner_failed','error':str(exc)}
            cohort['results'].append(result);cohort['updated_at']=time.time();atomic_json(manifest,cohort)
            print(json.dumps(result),flush=True)
    cohort['finished_at']=time.time();atomic_json(manifest,cohort)

if __name__=='__main__':main()
