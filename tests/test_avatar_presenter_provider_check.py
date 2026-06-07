from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "avatar_presenter_provider_check.py"
    spec = importlib.util.spec_from_file_location("avatar_presenter_provider_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_avatar_presenter_provider_check_fails_closed_without_verified_avatar_renderer(tmp_path: Path) -> None:
    module = _load_script()

    payload = module.build_payload()

    assert payload["verdict"] == "READY_VIA_FALLBACK"
    assert payload["avatar_provider_ready"] is False
    assert payload["fallback_mode"] == "fallback_static_storyboard"
    providers = {row["provider"]: row for row in payload["providers"]}
    assert providers["VidBoard"]["status"] == "pilot"
    assert providers["VidBoard"]["lip_sync_verified"] is False
    assert providers["Nonverbia"]["status"] == "pilot"
    assert providers["Unmixr AI"]["max_resolution"] == "audio_only"
    assert providers["BrowserAct"]["status"] == "verified"

    output_path = tmp_path / "AVATAR_PRESENTER_PROVIDER_VERIFICATION.generated.json"
    module.write_payload(output_path)
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["contract_name"] == "executive_assistant.avatar_presenter_provider_verification.v1"
    assert written["providers"][0]["provider"] == "VidBoard"
