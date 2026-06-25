from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def load_root_script_module(script_name: str) -> ModuleType:
    repo_root = Path(__file__).resolve().parents[2]
    target = repo_root / "scripts" / f"{script_name}.py"
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    spec = importlib.util.spec_from_file_location(f"root_{script_name}", target)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable_to_load_root_script:{script_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def export_root_script(script_name: str, caller_globals: dict[str, Any]) -> ModuleType:
    module = load_root_script_module(script_name)
    for name in dir(module):
        if name.startswith("__") and name not in {"__all__"}:
            continue
        caller_globals[name] = getattr(module, name)
    return module
