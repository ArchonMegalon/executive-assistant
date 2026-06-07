from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_avatar_presenter_provider.py"
    spec = importlib.util.spec_from_file_location("verify_avatar_presenter_provider", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_verify_vidboard_avatar_provider_fails_closed_without_proof(tmp_path: Path) -> None:
    module = _load_script()

    payload = module.build_payload("vidboard", allow_fallback=True)

    assert payload["provider"] == "VidBoard"
    assert payload["verdict"] == "READY_VIA_FALLBACK"
    assert payload["provider_ready"] is False
    assert payload["fallback_mode"] == "fallback_static_storyboard"
    assert payload["verification_checklist"]["lip_sync_quality"]["verified"] is False
    assert payload["verification_checklist"]["watermark_free_export"]["verified"] is False

    path = module.write_payload(payload, tmp_path)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["provider_key"] == "vidboard"


def test_verify_nonverbia_avatar_provider_returns_not_ready_without_fallback() -> None:
    module = _load_script()

    payload = module.build_payload("nonverbia", allow_fallback=False)

    assert payload["provider"] == "Nonverbia"
    assert payload["verdict"] == "NOT_READY"
    assert payload["provider_ready"] is False
