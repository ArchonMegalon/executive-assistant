from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "chummer6_overlay_vision_readiness.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("chummer6_overlay_vision_readiness", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_base_urls_derives_ollama_routes_from_comfyui_host(monkeypatch) -> None:
    readiness = _load_module()
    monkeypatch.setattr(readiness, "LOCAL_ENV", {"COMFYUI_URL": "https://images.example"})
    monkeypatch.setattr(readiness, "POLICY_ENV", {})

    candidates = readiness.candidate_base_urls()

    assert candidates == [
        "http://images.example:11434",
        "https://images.example/ollama",
    ]


def test_overlay_vision_readiness_pulls_missing_model_when_requested(monkeypatch) -> None:
    readiness = _load_module()
    monkeypatch.setattr(readiness, "LOCAL_ENV", {"CHUMMER6_OLLAMA_URL": "https://images.example/ollama"})
    monkeypatch.setattr(readiness, "POLICY_ENV", {})
    monkeypatch.setattr(readiness, "candidate_base_urls", lambda: ["https://images.example/ollama"])

    seen = {"list_calls": 0, "pull": 0}

    def fake_list_models(base_url: str, *, timeout_seconds=None):
        seen["list_calls"] += 1
        if seen["list_calls"] == 1:
            return [], ""
        return ["llama3.2-vision:11b"], ""

    def fake_pull_model(*, base_url: str, model: str, timeout_seconds=None):
        seen["pull"] += 1
        assert base_url == "https://images.example/ollama"
        assert model == "llama3.2-vision:11b"
        return True, ""

    monkeypatch.setattr(readiness, "list_models", fake_list_models)
    monkeypatch.setattr(readiness, "pull_model", fake_pull_model)

    report = readiness.overlay_vision_readiness(model="llama3.2-vision:11b", pull=True)

    assert report["status"] == "ready"
    assert report["endpoint_reachable"] is True
    assert report["model_ready"] is True
    assert report["pull_attempted"] is True
    assert report["pull_succeeded"] is True
    assert seen["pull"] == 1
    assert seen["list_calls"] == 2


def test_overlay_vision_readiness_reports_unreachable_endpoint(monkeypatch) -> None:
    readiness = _load_module()
    monkeypatch.setattr(readiness, "candidate_base_urls", lambda: ["https://images.example/ollama"])
    monkeypatch.setattr(readiness, "list_models", lambda base_url, timeout_seconds=None: (None, "http_502:bad gateway"))

    report = readiness.overlay_vision_readiness(model="llama3.2-vision:11b", pull=False)

    assert report["status"] == "endpoint_unreachable"
    assert report["endpoint_reachable"] is False
    assert report["detail"] == "http_502:bad gateway"
