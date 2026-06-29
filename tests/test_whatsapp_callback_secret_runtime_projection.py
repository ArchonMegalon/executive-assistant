from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_whatsapp_callback_secret_runtime_projection.py"


def _module():
    spec = importlib.util.spec_from_file_location("materialize_whatsapp_callback_secret_runtime_projection", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_materializes_ignored_runtime_projection_without_reporting_secret(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "config" / "whatsapp_audiobook_callback_secret"
    target = tmp_path / ".runtime" / "secrets" / "whatsapp_audiobook_callback_secret"
    source.parent.mkdir()
    source.write_text("callback-secret\n", encoding="utf-8")
    source.chmod(0o600)

    result = module.materialize_projection(root=tmp_path, source=source, target=target)

    assert result["status"] == "ready"
    assert result["secret_present"] is True
    assert result["target_parent_mode"] == "0o700"
    assert result["target_mode"] in {"0o400", "0o444"}
    assert target.read_text(encoding="utf-8") == "callback-secret\n"
    assert "callback-secret" not in str(result)


def test_missing_source_creates_empty_mount_placeholder(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "config" / "missing"
    target = tmp_path / ".runtime" / "secrets" / "whatsapp_audiobook_callback_secret"

    result = module.materialize_projection(root=tmp_path, source=source, target=target)

    assert result["status"] == "skipped"
    assert result["reason"] == "source_secret_missing_or_empty"
    assert result["secret_present"] is False
    assert target.exists()
    assert target.read_text(encoding="utf-8") == ""
