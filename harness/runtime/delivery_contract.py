"""Load a frozen, visibility-separated delivery agreement; never infer from scores."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

CONTRACT_NAME = 'delivery_contract.json'
README_MARKER = '\n\n<!-- delivery-contract -->\n'

def require_experiment_ready(dataset: Path) -> None:
    status=Path(dataset)/'release_status.json'
    if status.exists() and json.loads(status.read_text()).get('experiment_ready') is not True:
        raise ValueError('Dataset is review-only, not qualified for scored experiments; see release_status.json')

def readme_projection(document: dict[str, Any]) -> str:
    return document['public']['readme'].rstrip() + README_MARKER + (
        '## Delivery agreement\n\n'
        'The public interface is also available in `DELIVERY_INTERFACE.json`. '
        'Its field names, signatures, defaults and error shapes are fixed; '
        'clarification may explain them but must not rename or contradict them. '
        'Business decisions intentionally left open above remain questions for the client. '
        'If a reply conflicts with this agreement, request a correction.\n'
    )

def public_projection(document: dict[str, Any]) -> dict[str, Any]:
    return {'schema_version':1, 'contract_version':document['contract_version'],
            'task_id':document['task_id'], **document['public']}

def safe_file(root: Path, relative: str) -> Path:
    raw=root/relative
    path=raw.resolve()
    if raw.is_symlink() or not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'Unsafe or missing contract input: {relative}')
    return path

def load_delivery_contract(task_dir: Path, registry=None) -> dict[str, Any] | None:
    task_dir=Path(task_dir)
    path=task_dir/'evaluation'/CONTRACT_NAME
    if not path.exists():
        # Tasks without a contract must not expose an unauthenticated public projection.
        if (task_dir/'workspace/DELIVERY_INTERFACE.json').exists():
            raise ValueError('Public contract exists without authoritative private contract')
        return None
    document=json.loads(safe_file(task_dir,'evaluation/'+CONTRACT_NAME).read_text())
    if document.get('schema_version')!=1 or document.get('task_id')!=task_dir.name:
        raise ValueError('Delivery contract identity/schema mismatch')
    public=document.get('public',{})
    if set(public)!={'readme','interfaces'} or not isinstance(public['readme'],str) or not isinstance(public['interfaces'],list):
        raise ValueError('Invalid public projection fields')
    if safe_file(task_dir,'evaluation/project/README.md').read_text()!=readme_projection(document):
        raise ValueError('README differs from canonical delivery contract')
    actual=json.loads(safe_file(task_dir,'evaluation/project/DELIVERY_INTERFACE.json').read_text())
    if actual!=public_projection(document):
        raise ValueError('Public interface differs from canonical delivery contract')
    if registry is not None:
        expected={u.ru_id:u.test_interface.model_dump(mode='json') for u in registry.slots}
        if document['interfaces_by_ru']!=expected:
            raise ValueError('RU interfaces differ from canonical delivery contract')
        # This projection is private Client context. It is
        # never copied into the candidate workspace or initial prompt.
        if (task_dir/'workspace/README.md').exists() or (task_dir/'workspace/DELIVERY_INTERFACE.json').exists():
            raise ValueError('Pilot private project documents leaked into workspace')
        if document['requirements_sha256']!=hashlib.sha256(safe_file(task_dir,'evaluation/requirement_units.yaml').read_bytes()).hexdigest():
            raise ValueError('Requirement text changed without contract review')
    actual_sources={p.relative_to(task_dir).as_posix():hashlib.sha256(safe_file(task_dir,p.relative_to(task_dir).as_posix()).read_bytes()).hexdigest()
                    for p in (task_dir/'evaluation/tests').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
    if actual_sources!=document['test_sources_sha256']:
        raise ValueError('Acceptance tests changed without contract review')
    if document.get('public_environment_sha256') is not None:
        from .public_sources import public_source_digest
        observed = public_source_digest(task_dir)
        # Standalone copied test fixtures have no dataset/environment catalog.
        if observed is not None and observed != document['public_environment_sha256']:
            raise ValueError('Public environment manifest changed without contract review')
    return document

def private_project_context(task_dir: Path, registry, *, workspace: str | None = None) -> tuple[dict[str, Any],list[dict[str,Any]]]:
    document=load_delivery_contract(task_dir,registry)
    if document is None:
        return {},[]
    root=Path(task_dir)
    environment=json.loads(safe_file(root,'environment.json').read_text())
    declared_workspace=environment['workdir']
    workspace=workspace or declared_workspace
    if workspace != declared_workspace:
        raise ValueError('Runtime workspace differs from task environment workdir')
    if not workspace.startswith('/') or workspace=='/' or '..' in PurePosixPath(workspace).parts:
        raise ValueError('Invalid task workspace')
    workspace=workspace.rstrip('/')
    roots=[];catalog=[];requirements=[]
    # Exact-file manifests prevent an unreviewed new file under an otherwise
    # allowed directory from silently becoming visible. Hashes are rechecked on
    # every read. Never map the whole task or its parent directory.
    for relative,virtual,category in [
        ('workspace',workspace,'public_starter'),
        ('public_tests','/public_tests','public_checks'),
        ('attachments',workspace+'/task_attachments','public_attachments'),
        ('evaluation/tests','/private_acceptance','private_acceptance'),
        ('evaluation/project','/project_documents','private_project_documents'),
    ]:
        directory=root/relative
        if not directory.is_dir():continue
        files={}
        for p in sorted(directory.rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts or p.suffix in {'.pyc','.pyo'}:continue
            p=safe_file(root,p.relative_to(root).as_posix())
            name=p.relative_to(directory.resolve()).as_posix()
            files[name]=hashlib.sha256(p.read_bytes()).hexdigest()
            catalog.append({'path':virtual+'/'+name,'bytes':p.stat().st_size,'category':category})
        roots.append({'virtual':virtual,'real':str(directory.resolve()),'files':files,
                      **({'workspace':True} if relative=='workspace' else {})})
    from .public_sources import public_source_roots
    for source in public_source_roots(root):
        roots.append(source)
        catalog.append({'path':source['virtual'],'bytes':Path(source['real']).stat().st_size,
                        'category':'public_environment_source'})
    for relative,virtual in [('request.md','/task/request.md'),('environment.json','/task/environment.json'),
                             ('evaluation/client_context.json','/project_context/client_context.json')]:
        if not (root/relative).is_file():continue
        p=safe_file(root,relative)
        roots.append({'virtual':virtual,'real':str(p),'files':{'':hashlib.sha256(p.read_bytes()).hexdigest()}})
        catalog.append({'path':virtual,'bytes':p.stat().st_size,'category':'project_context'})
    for i,unit in enumerate(registry.slots,1):
        path=f'/requirements/{i:03}.json'
        content=json.dumps({'name':unit.name,'content':unit.content,
                            'test_interface':unit.test_interface.model_dump(mode='json')},ensure_ascii=False,indent=2)
        # In-memory private files: full text is sent to the local read tool, not
        # to the model prompt until requested. No audit rubric or old result.
        roots.append({'virtual':path,'content':content})
        requirements.append({'name':unit.name,'path':path,'bytes':len(content.encode())})
    context={'contract_version':document['contract_version'],'context_protocol':'role-context.v3-elicitation',
             'job_description':safe_file(root,'request.md').read_text(),
             'workspace_path':workspace,
             'readme_path':'/project_documents/README.md',
             'public_interface_path':'/project_documents/DELIVERY_INTERFACE.json',
             'project_readme':safe_file(root,'evaluation/project/README.md').read_text(),
             'delivery_agreement':document['public']['interfaces'],
             'requirement_catalog':requirements,'file_catalog':catalog,
             'policy':'Full requirement content/interfaces and project README are supplied inline. Answer only relevant questions. '
                      'Follow imports into public_tests, frozen starter sources, or indexed /opt/sweclar public environment sources as needed. '
                      'Acceptance tests corroborate the contract, never create undocumented obligations. '
                      'All files are read-only frozen task inputs, not the live candidate implementation. '
                      'No test code, fixture answers or unrelated hidden requirements may be disclosed.'}
    return context,roots
