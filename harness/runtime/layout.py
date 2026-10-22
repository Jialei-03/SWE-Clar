"""Dataset paths shared by headless execution and optional platform adapters."""
from pathlib import Path

def is_release_layout(task):
    return (Path(task) / "evaluation/requirement_units.yaml").is_file()

def requirements_path(task):
    task = Path(task)
    return task / ("evaluation/requirement_units.yaml" if is_release_layout(task) else "requirement_units.yaml")

def input_path(task):
    task = Path(task)
    return task / ("input.yaml" if is_release_layout(task) else "benchmark_input.yaml")

def workspace_path(task):
    task = Path(task)
    if is_release_layout(task):
        return task / "workspace"
    raw = task / "raw"
    if not raw.is_dir():
        raw = task.parent / "raw"
    return raw / "starter_code"

def attachment_root(task):
    task = Path(task)
    if is_release_layout(task):
        return task / "attachments"
    return workspace_path(task).parent / "attachments"
