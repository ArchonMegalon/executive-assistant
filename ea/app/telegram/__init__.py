from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# --- EA v1.12.10 telegram legacy bridge ---
_LEGACY_PATH = Path(__file__).resolve().parent.parent / "telegram.py"
_SPEC = importlib.util.spec_from_file_location("app._legacy_telegram_impl", _LEGACY_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load legacy telegram module from {_LEGACY_PATH}")
_legacy = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("app._legacy_telegram_impl", _legacy)
_SPEC.loader.exec_module(_legacy)

for _name in [n for n in dir(_legacy) if not n.startswith("_")]:
    globals()[_name] = getattr(_legacy, _name)

from .safety import SAFE_PLACEHOLDER_COPY, SAFE_SIMPLIFIED_COPY, install_telegram_safety, sanitize_telegram_text

try:
    _patched = install_telegram_safety(globals().get("TelegramClient")) if globals().get("TelegramClient") else []
    print(f"[EA TELEGRAM SAFETY] patched methods={_patched}")
except Exception as _ea_tg_safe_err:
    print(f"[EA TELEGRAM SAFETY BOOTSTRAP WARNING] {_ea_tg_safe_err}")


def __getattr__(name):
    return getattr(_legacy, name)
