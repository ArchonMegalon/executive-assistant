from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "patch_whatsapp_web_session_runtime.py"


def _module():
    spec = importlib.util.spec_from_file_location("patch_whatsapp_web_session_runtime", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_patch_runner_source_delegates_whatsapp_recovery_to_outbox_helper() -> None:
    module = _module()
    source = """from app.services import whatsapp_delivery

def before():
    pass

def _run_scheduler_whatsapp_async_recovery(container, log: logging.Logger) -> dict[str, object]:  # type: ignore[no-untyped-def]
    drained = 0
    return {"ran": True, "drained": drained}

def after():
    pass
"""

    patched = module._patch_runner_source(source)

    assert "from app.services import whatsapp_delivery_outbox" in patched
    assert "return whatsapp_delivery_outbox.drain_whatsapp_delivery_outbox(" in patched
    assert "min_age_seconds=max(_scheduler_whatsapp_async_recovery_min_age_seconds(), 2.0)" in patched
    assert "max_attempts=_whatsapp_queue_max_attempts()" in patched
    assert "def after():" in patched
    assert "drained = 0" not in patched


def test_patch_runner_source_is_idempotent() -> None:
    module = _module()
    source = """from app.services import whatsapp_delivery

def _run_scheduler_whatsapp_async_recovery(container, log: logging.Logger) -> dict[str, object]:  # type: ignore[no-untyped-def]
    drained = 0
    return {"ran": True, "drained": drained}
"""

    once = module._patch_runner_source(source)
    twice = module._patch_runner_source(once)

    assert once == twice


def test_runtime_patch_declares_api_channels_patch_contract() -> None:
    module = _module()

    assert module.API_SERVICE_MODULES == (
        "whatsapp_web_session_delivery.py",
        "whatsapp_delivery_router.py",
    )
    assert module.CHANNELS_PATH == "/app/app/api/routes/channels.py"
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "--patch-api-channels" in source
    assert "def _verify_api_container(" in source
    assert "def _whatsapp_send_audiobook_voice_samples(" in source
    assert "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET" in source
