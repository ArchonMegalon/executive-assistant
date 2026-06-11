"""Support importing ``scripts.*`` modules from both script roots."""

from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[name-defined]

_ROOT_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if _ROOT_SCRIPTS.is_dir():
    __path__.append(str(_ROOT_SCRIPTS))  # type: ignore[name-defined]
