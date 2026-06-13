from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_expensive_pr_jobs_require_manual_dispatch_or_full_budget_mode() -> None:
    smoke = (ROOT / ".github/workflows/smoke-runtime.yml").read_text(encoding="utf-8")
    memorial = (ROOT / ".github/workflows/memorial-security.yml").read_text(encoding="utf-8")

    budget_guard = "github.event_name == 'workflow_dispatch' || vars.EA_CI_BUDGET_MODE == 'full'"
    for job_name in (
        "security-static:",
        "product-browser-e2e:",
        "smoke-runtime-api:",
        "generated-release-artifacts-clean:",
    ):
        section = smoke[smoke.index(job_name) : smoke.index("runs-on:", smoke.index(job_name))]
        assert budget_guard in section

    section = memorial[memorial.index("memorial-browser-e2e:") : memorial.index("runs-on:", memorial.index("memorial-browser-e2e:"))]
    assert budget_guard in section


def test_public_origin_gold_workflow_collects_room_audio_receipt() -> None:
    workflow = (ROOT / ".github/workflows/memorial-public-gold.yml").read_text(encoding="utf-8")

    assert "room_reviewer:" in workflow
    assert "MEMORIAL_ROOM_REVIEWER" in workflow
    assert "memorial_room_audio_public_origin.generated.json" in workflow
    assert "make materialize-memorial-public-gold" in workflow
