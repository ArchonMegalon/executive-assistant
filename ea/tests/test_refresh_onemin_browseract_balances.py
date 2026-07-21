from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
REFRESH_SCRIPT_PATH = ROOT / "scripts" / "refresh_onemin_browseract_balances.py"


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_partial_timeout_recovers_onemin_home_credit_badge(monkeypatch) -> None:
    module = _load_script(REFRESH_SCRIPT_PATH, "refresh_onemin_browseract_balances_test")
    record = module.AccountRecord(
        slot="slot-1",
        account_label="ONEMIN_AI_API_KEY",
        owner_email="tibor.girschele@gmail.com",
        owner_name="Tibor Girschele",
    )
    response = {
        "structured_output_json": {
            "extracts": {
                "home_after_login": (
                    "T\n"
                    "Tibor Girschele\n\n"
                    "Team\n\n"
                    "1min.AI\n"
                    "90,279\n"
                    "Magic Notebook\n"
                    "AI DISCOVERY\n"
                ),
            }
        },
        "warnings": ["timeout_stage:wait_billing_usage"],
        "asset_path": "/tmp/result.html",
        "screenshot_path": "/tmp/preview.png",
    }

    monkeypatch.setattr(
        module,
        "_persist_normalized_snapshot",
        lambda record, *, normalized: ({"remaining_credits": normalized.get("remaining_credits")}, ""),
    )

    recovered = module._recovered_partial_refresh_result(
        record,
        response=response,
        duration_seconds=171.0,
        worker_returncode=1,
        proxy_values={"EA_UI_BROWSER_PROXY_SERVER": "direct://", "EA_UI_BROWSER_PROXY_SERVICE_NAME": ""},
        recovery_reason="timeout",
    )

    assert recovered is not None
    assert recovered["status"] == "ok"
    assert recovered["remaining_credits"] == 90279
    assert recovered["basis"] == "actual_home_credit_badge"
    assert "recovered_from_timeout" in recovered["warnings"]
