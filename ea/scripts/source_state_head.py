from __future__ import annotations

try:
    from scripts._root_script_proxy import export_root_script
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from _root_script_proxy import export_root_script

_module = export_root_script("source_state_head", globals())

if __name__ == "__main__" and hasattr(_module, "main"):
    raise SystemExit(_module.main())
