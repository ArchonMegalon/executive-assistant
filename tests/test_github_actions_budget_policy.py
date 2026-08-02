from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_github_actions_workflows_are_removed() -> None:
    workflows_dir = ROOT / ".github" / "workflows"

    assert not workflows_dir.exists()


def test_former_actions_gates_remain_available_as_local_commands() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    operator_summary = (ROOT / "scripts/operator_summary.sh").read_text(encoding="utf-8")

    assert "ci-gates:" in makefile
    assert "release-smoke:" in makefile
    assert "release-preflight:" in makefile
    assert "verify-whole-project-gold-map" in makefile
    assert "verify-project-mode-runtime" in makefile
    assert "make release-preflight" in readme
    assert "make release-preflight" in runbook
    assert "GitHub Actions workflows are intentionally not tracked in this repo." in readme
    assert "Hosted GitHub Actions workflows are intentionally absent from this repo." in runbook
    assert "hosted CI:         intentionally absent; use local gate bundles below" in operator_summary
