from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_poppy_playwright_workdir_defaults_to_ea_root(monkeypatch) -> None:
    monkeypatch.delenv("POPPY_PLAYWRIGHT_WORKDIR", raising=False)

    module = _load_script("capture_poppy_provider_receipts.py")
    host_specific_run_services = "/docker/chummercomplete/" + "chummer.run-services"

    assert module.PLAYWRIGHT_WORKDIR == ROOT
    assert host_specific_run_services not in (ROOT / "scripts" / "capture_poppy_provider_receipts.py").read_text(
        encoding="utf-8"
    )


def test_poppy_completion_paths_default_to_repo_local(monkeypatch) -> None:
    monkeypatch.delenv("POPPY_COMPLETION_DIR", raising=False)
    monkeypatch.delenv("POPPY_PROVIDER_ACCESS_PROBE_OUTPUT", raising=False)
    monkeypatch.delenv("POPPY_PROVIDER_SESSION_PROBE_PATH", raising=False)
    monkeypatch.delenv("POPPY_BROWSERACT_PUBLISH_PROBE_OUTPUT", raising=False)
    monkeypatch.delenv("POPPY_BROWSERACT_WORKFLOW_SPEC", raising=False)

    capture = _load_script("capture_poppy_provider_receipts.py")
    provider = _load_script("probe_poppy_ai_provider.py")
    browseract = _load_script("probe_poppy_ai_browseract_publish.py")
    draft = _load_script("materialize_poppy_draft_workbench_receipts.py")
    expected_dir = ROOT / "ea/_completion/poppy_ai"

    assert capture.OUT_DIR == expected_dir
    assert provider.DEFAULT_COMPLETION_DIR == expected_dir
    assert provider.DEFAULT_OUTPUT == expected_dir / "POPPY_AI_PROVIDER_ACCESS_PROBE.generated.json"
    assert provider.SESSION_PROBE_PATH == expected_dir / "POPPY_AI_PROVIDER_SESSION_PROBE.generated.json"
    assert browseract.DEFAULT_COMPLETION_DIR == expected_dir
    assert browseract.OUTPUT == expected_dir / "POPPY_AI_BROWSERACT_PUBLISH_PROBE.generated.json"
    assert browseract.WORKFLOW_SPEC == ROOT / "browseract_templates/poppy_ai_login_surface_reader.workflow.json"
    assert draft.DEFAULT_POPPY_COMPLETION_DIR == expected_dir
    assert draft.DEFAULT_SESSION_PROBE == expected_dir / "POPPY_AI_PROVIDER_SESSION_PROBE.generated.json"

    rendered = "\n".join(
        (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for name in (
            "capture_poppy_provider_receipts.py",
            "probe_poppy_ai_provider.py",
            "probe_poppy_ai_browseract_publish.py",
            "materialize_poppy_draft_workbench_receipts.py",
        )
    )
    host_specific_completion = "/docker/chummercomplete/" + ".integrated/fleet/_completion/poppy_ai"
    assert host_specific_completion not in rendered


def test_poppy_completion_paths_honor_env_overrides(monkeypatch, tmp_path: Path) -> None:
    completion_dir = tmp_path / "poppy"
    access_output = tmp_path / "access.json"
    session_probe = tmp_path / "session.json"
    browseract_output = tmp_path / "browseract.json"
    workflow_spec = tmp_path / "workflow.json"
    monkeypatch.setenv("POPPY_COMPLETION_DIR", str(completion_dir))
    monkeypatch.setenv("POPPY_PROVIDER_ACCESS_PROBE_OUTPUT", str(access_output))
    monkeypatch.setenv("POPPY_PROVIDER_SESSION_PROBE_PATH", str(session_probe))
    monkeypatch.setenv("POPPY_BROWSERACT_PUBLISH_PROBE_OUTPUT", str(browseract_output))
    monkeypatch.setenv("POPPY_BROWSERACT_WORKFLOW_SPEC", str(workflow_spec))

    provider = _load_script("probe_poppy_ai_provider.py")
    browseract = _load_script("probe_poppy_ai_browseract_publish.py")
    draft = _load_script("materialize_poppy_draft_workbench_receipts.py")

    assert provider.DEFAULT_COMPLETION_DIR == completion_dir
    assert provider.DEFAULT_OUTPUT == access_output
    assert provider.SESSION_PROBE_PATH == session_probe
    assert browseract.OUTPUT == browseract_output
    assert browseract.WORKFLOW_SPEC == workflow_spec
    assert draft.DEFAULT_POPPY_COMPLETION_DIR == completion_dir
    assert draft.DEFAULT_SESSION_PROBE == session_probe
