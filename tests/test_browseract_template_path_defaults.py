from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "browseract_templates"


def test_browseract_templates_use_repo_local_runtime_output_dir() -> None:
    paths = sorted(TEMPLATE_ROOT.glob("*.json"))
    assert paths

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("meta")
        if isinstance(meta, dict) and "output_dir" in meta:
            output_dir = str(meta["output_dir"])
            assert output_dir == ".codex-studio/published/browseract_bootstrap", path


def test_browseract_template_generators_default_to_published_state() -> None:
    rendered = "\n".join(
        [
            (ROOT / "scripts" / "browseract_bootstrap_manager.py").read_text(encoding="utf-8"),
            (ROOT / "scripts" / "export_browseract_ui_service_templates.py").read_text(encoding="utf-8"),
        ]
    )

    assert ".codex-studio" in rendered
    assert "published" in rendered
    assert "/docker/" + "fleet" not in rendered
    bad_runtime_default = '"' + ".runtime" + '" / "browseract_bootstrap"'
    assert bad_runtime_default not in rendered


def test_browseract_template_worker_defaults_are_repo_local() -> None:
    source = (ROOT / "scripts" / "browseract_template_service_worker.py").read_text(encoding="utf-8")

    assert 'Path("/mnt/' + 'onedrive/Attachments")' not in source
    assert 'ROOT / ".runtime" / "browseract"' in source
    assert "EA_UI_SERVICE_WORKER_OUTPUT_ROOT" in source
    assert "EA_UI_SERVICE_SHARED_TEMP_ROOT" in source


def test_browseract_tool_adapter_worker_defaults_are_repo_local() -> None:
    source = (ROOT / "ea" / "app" / "services" / "tool_execution_browseract_adapter.py").read_text(encoding="utf-8")

    assert "/mnt/" + "pcloud" not in source
    assert "/docker/" + "EA/scripts" not in source
    assert '"browseract_ui_worker_outputs"' in source
    assert '"browseract_ui_worker_shared"' in source


def test_browseract_content_generator_uses_generic_default_principal() -> None:
    source = (ROOT / "scripts" / "generate_browseract_content_templates.py").read_text(encoding="utf-8")

    assert 'X-EA-Principal-ID": "exec-1"' not in source
    assert "EA_DEFAULT_PRINCIPAL_ID" in source
    assert "principal-default" in source
