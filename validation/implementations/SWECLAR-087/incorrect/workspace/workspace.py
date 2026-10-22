import json
from pathlib import Path


def load_workspace(workspace):
    root=Path(workspace).resolve()
    config=json.loads((root/'sync.json').read_text())
    return root,config
