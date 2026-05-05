from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer_explain_narration_packs" / "CHUMMER_EXPLAIN_NARRATION_PACKET_PACK.yaml"
SPECIMENS_PATH = ROOT / "docs" / "chummer_explain_narration_packs" / "GROUNDED_FOLLOW_UP_SPECIMENS.yaml"
README_PATH = ROOT / "docs" / "chummer_explain_narration_packs" / "README.md"
HANDOFF_CLOSEOUT_PATH = ROOT / "docs" / "chummer_explain_narration_packs" / "SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
SKILL_PATH = ROOT / "skills" / "chummer_grounded_explain_narration" / "SKILL.md"
FEEDBACK_PATH = ROOT / "feedback" / "2026-05-05-ea-grounded-explain-narration-packs-package-closeout.md"
QUEUE_STAGING_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
DESIGN_QUEUE_STAGING_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")


def _yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def test_pack_identity_and_scope() -> None:
    pack = _yaml(PACK_PATH)
    assert pack.get("contract_name") == "ea.chummer_explain_narration_packet_pack"
    assert pack.get("package_id") == "next90-m145-ea-grounded-explain-narration-packs"
    assert int(pack.get("milestone_id") or 0) == 145
    assert list(pack.get("owned_surfaces") or []) == [
        "explain_packet_narration:ea",
        "grounded_follow_up_compile:ea",
    ]
    labels = list(dict(pack.get("quality_gates") or {}).get("required_labels") or [])
    assert labels == ["packet_grounded", "text_first_fallback", "no_arithmetic_authority"]


def test_specimens_share_bundle_and_cover_refusal_flow() -> None:
    pack = _yaml(PACK_PATH)
    specimens = _yaml(SPECIMENS_PATH)
    assert specimens.get("shared_truth_bundle_id") == dict(pack.get("governed_truth_bundle") or {}).get("bundle_id")
    rows = list(specimens.get("specimens") or [])
    assert len(rows) >= 5
    assert {dict(row).get("question_class") for row in rows} == {
        "why",
        "why_not",
        "what_if",
        "what_changed",
        "source_anchor",
    }
    refusal = next(row for row in rows if dict(row).get("specimen_id") == "missing-counterfactual-refusal")
    follow_up = dict(refusal.get("grounded_follow_up_pack") or {})
    assert follow_up.get("approved_answer") == "unavailable"
    assert "may not guess" in str(follow_up.get("answer_limits") or "")


def test_specimens_cover_source_anchor_and_diff_classes() -> None:
    specimens = _yaml(SPECIMENS_PATH)
    rows = list(specimens.get("specimens") or [])
    source_anchor = next(row for row in rows if dict(row).get("specimen_id") == "desktop-initiative-source-anchor")
    what_changed = next(row for row in rows if dict(row).get("specimen_id") == "mobile-armor-what-changed")
    assert dict(source_anchor.get("grounded_follow_up_pack") or {}).get("question_class") == "source_anchor"
    assert "Core Rulebook page 159" in str(dict(source_anchor.get("grounded_follow_up_pack") or {}).get("approved_answer") or "")
    assert dict(what_changed.get("grounded_follow_up_pack") or {}).get("question_class") == "what_changed"
    assert "drops the current armor total from 11 to 8" in str(dict(what_changed.get("grounded_follow_up_pack") or {}).get("approved_answer") or "")


def test_skill_restates_fail_closed_compile_order() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    for marker in (
        "Follow this order exactly:",
        "Never compute a new result.",
        "Never answer `why_not` or `what_if` without the required counterfactual or diff packet.",
        "unavailable: Chummer does not have the required packet-backed follow-up",
    ):
        assert marker in skill


def test_readme_and_feedback_point_at_same_package_scope() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    feedback = FEEDBACK_PATH.read_text(encoding="utf-8")
    assert "milestone `145`" in readme
    assert "`next90-m145-ea-grounded-explain-narration-packs`" in feedback
    assert "packet-grounded" in feedback


def test_handoff_is_worker_safe_and_bounded() -> None:
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    assert handoff.get("status") == "ea_scope_complete"
    assert list(handoff.get("closed_surfaces") or []) == [
        "explain_packet_narration:ea",
        "grounded_follow_up_compile:ea",
    ]
    assert list(dict(handoff.get("scope_boundary") or {}).get("allowed_paths") or []) == [
        "skills",
        "tests",
        "feedback",
        "docs",
    ]
    handoff_text = HANDOFF_CLOSEOUT_PATH.read_text(encoding="utf-8").lower()
    for marker in (
        "task_local_telemetry",
        "active_run_handoff",
        "/var/lib/codex-fleet",
        "supervisor status",
        "supervisor eta",
        "operator telemetry",
    ):
        assert marker in handoff_text


def test_queue_and_registry_show_active_m145_ea_lane() -> None:
    queue = _yaml(QUEUE_STAGING_PATH)
    design_queue = _yaml(DESIGN_QUEUE_STAGING_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)

    queue_row = next(item for item in queue.get("items") or [] if dict(item).get("package_id") == "next90-m145-ea-grounded-explain-narration-packs")
    design_queue_row = next(item for item in design_queue.get("items") or [] if dict(item).get("package_id") == "next90-m145-ea-grounded-explain-narration-packs")
    milestone = next(item for item in registry.get("milestones") or [] if int(dict(item).get("id") or 0) == 145)
    work_task = next(item for item in milestone.get("work_tasks") or [] if str(dict(item).get("id")) == "145.4")

    assert queue_row["status"] == design_queue_row["status"] == work_task["status"] == "done"
    assert any("CHUMMER_EXPLAIN_NARRATION_PACKET_PACK.yaml" in entry for entry in queue_row.get("proof") or [])
    assert any("chummer_grounded_explain_narration/SKILL.md" in entry for entry in queue_row.get("proof") or [])
    assert any("tests/test_next90_m145_grounded_explain_narration_packs.py" in entry for entry in queue_row.get("proof") or [])
    assert any("skills/chummer_grounded_explain_narration/SKILL.md" in entry for entry in work_task.get("evidence") or [])


def test_no_specimen_uses_guess_language() -> None:
    text = SPECIMENS_PATH.read_text(encoding="utf-8").lower()
    for marker in ("maybe the rule", "should be around", "probably"):
        assert marker not in text


def _run_direct() -> int:
    failed = 0
    ran = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        ran += 1
        try:
            func()
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"ran={ran} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_direct())
