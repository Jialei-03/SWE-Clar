from pathlib import Path

def within(root, relative):
    root=Path(root).resolve();candidate=(root/relative).resolve()
    if not candidate.is_relative_to(root) or candidate==root:raise ValueError("path leaves workspace")
    return candidate
