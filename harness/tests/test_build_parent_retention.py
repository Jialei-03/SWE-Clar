import importlib.util
import json
from pathlib import Path

def test_untagged_parent_survives_temporary_alias_removal(monkeypatch):
    root=Path(__file__).resolve().parents[2]/'SWE-Clar/environments'
    monkeypatch.syspath_prepend(str(root))
    spec=importlib.util.spec_from_file_location('frozen_retention',root/'frozen_extensions.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    identity='sha256:'+'a'*64
    tags=set();alive=True
    def inspect(argv):
        assert alive and (argv[-1]==identity or argv[-1] in tags)
        return json.dumps([{'Id':identity,'RepoTags':list(tags),'Architecture':'amd64','RootFS':{'Layers':['layer']}}])
    def run(argv,**kwargs):
        nonlocal alive
        if argv[1]=='tag':tags.add(argv[-1])
        elif argv[1:3]==['image','rm']:
            tags.remove(argv[-1]);alive=bool(tags)
        else:raise AssertionError(argv)
    monkeypatch.setattr(module.subprocess,'run',run)
    for _ in range(2):
        with module.pinned_base(identity,inspect) as (alias,parent):assert alias in tags
        assert alive
    assert tags=={'swe-clar-build-cache:'+'a'*64}
