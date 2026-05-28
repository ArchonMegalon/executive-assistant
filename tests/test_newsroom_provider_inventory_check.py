from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "newsroom_provider_inventory_check.py"
    spec = importlib.util.spec_from_file_location("newsroom_provider_inventory_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_newsroom_provider_inventory_check_fails_closed_without_verified_host_renderer(tmp_path: Path) -> None:
    module = _load_script()

    payload = module.build_payload()

    assert payload["verdict"] == "NOT_READY"
    assert payload["photoreal_host_render_ready"] is False
    providers = {row["provider"]: row for row in payload["providers"]}
    assert providers["BrowserAct"]["status"] == "verified"
    assert providers["Emailit"]["status"] == "verified"
    assert providers["Mootion"]["status"] == "pilot"
    assert providers["VidBoard"]["commercial_use_allowed"] is False

    output_path = tmp_path / "NEWSROOM_PROVIDER_VERIFICATION.generated.json"
    module.write_payload(output_path)
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["providers"][0]["provider"] == "Blip AI"
