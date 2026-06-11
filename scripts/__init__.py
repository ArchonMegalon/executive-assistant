"""Repository script namespace for tests and local automation.

Root-level scripts and package-local memorial scripts are both exposed under
``scripts.*`` so tests can import the operational helpers without installing
the repository as a package.
"""

from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[name-defined]

_EA_SCRIPTS = Path(__file__).resolve().parents[1] / "ea" / "scripts"
if _EA_SCRIPTS.is_dir():
    __path__.append(str(_EA_SCRIPTS))  # type: ignore[name-defined]
