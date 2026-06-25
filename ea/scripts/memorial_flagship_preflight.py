from __future__ import annotations
from _root_script_proxy import export_root_script

_module = export_root_script("memorial_flagship_preflight", globals())

if __name__ == "__main__":
    raise SystemExit(_module.main())
