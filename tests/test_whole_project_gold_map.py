from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts import materialize_whole_project_gold_map as materialize
from scripts import verify_whole_project_gold_map as verifier


def test_whole_project_gold_map_accepts_repo_relative_output_path() -> None:
    receipt = materialize.build_gold_map(
        output_path=Path(".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"),
        generated_at="2026-06-12T00:00:00Z",
    )
    assert receipt["output_path"] == ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"


def test_whole_project_gold_map_is_conservative_and_repo_bounded() -> None:
    receipt = materialize.build_gold_map(generated_at="2026-06-12T00:00:00Z")
    planes = {plane["key"]: plane for plane in receipt["planes"]}

    assert set(planes) == verifier.REQUIRED_PLANES
    assert receipt["overall_status"] == "not_gold"
    assert receipt["gold_claim_allowed"] is False
    assert "design_surface" in receipt["blocking_planes"]
    assert "ltd_provider_lanes" in receipt["blocking_planes"]
    assert receipt["ltd_provider_lane_summary"]["poppy_runtime_enabled"] is False
    assert all("memorial" not in key.lower() for key in planes)
    assert "owning repository" in receipt["claim_scope_label"]


def test_whole_project_gold_map_verifier_rejects_gold_overclaim(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = materialize.build_gold_map(generated_at="2026-06-12T00:00:00Z")
    path = tmp_path / "gold-map.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(verifier, "resolve_source_state_head", lambda _root: receipt["source_git_head"])
    assert verifier.verify(path) == []

    overclaim = copy.deepcopy(receipt)
    overclaim["overall_status"] = "gold"
    overclaim["gold_claim_allowed"] = True
    path.write_text(json.dumps(overclaim), encoding="utf-8")
    issues = verifier.verify(path)
    assert any("gold_claim_allowed cannot be true" in issue for issue in issues)
    assert any("overall_status cannot be gold" in issue for issue in issues)


def test_whole_project_gold_map_source_head_uses_source_state(monkeypatch) -> None:
    monkeypatch.setattr(materialize, "resolve_source_state_head", lambda _root: "SOURCE_HEAD")
    receipt = materialize.build_gold_map(generated_at="2026-06-12T00:00:00Z")
    assert receipt["source_git_head"] == "SOURCE_HEAD"


def test_whole_project_gold_map_promotes_telegram_video_only_with_live_receipt(
    tmp_path: Path,
) -> None:
    operator = tmp_path / "telegram_video_delivery_operator.generated.json"
    live = tmp_path / "telegram_video_delivery_live.generated.json"
    operator.write_text(
        json.dumps({"status": "bounded_pass", "blocking_checks": []}),
        encoding="utf-8",
    )
    live.write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    receipt = materialize.build_gold_map(
        telegram_video_delivery_receipt=operator,
        telegram_video_delivery_live_receipt=live,
        generated_at="2026-06-18T10:00:00Z",
    )
    plane = next(row for row in receipt["planes"] if row["key"] == "telegram_video_delivery")
    assert plane["status"] == "pass"
    assert plane["missing_evidence"] == []


def test_write_json_stable_ignores_only_generation_time(tmp_path: Path) -> None:
    path = tmp_path / "gold-map.json"
    first = {"generated_at": "first", "status": "pass"}
    second = {"generated_at": "second", "status": "pass"}
    materialize.write_json_stable(path, first)
    before = path.read_text(encoding="utf-8")
    materialize.write_json_stable(path, second)
    assert path.read_text(encoding="utf-8") == before
