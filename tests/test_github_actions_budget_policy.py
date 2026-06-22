from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_github_actions_workflows_are_removed() -> None:
    workflows_dir = ROOT / ".github" / "workflows"

    assert not workflows_dir.exists()


def test_former_actions_gates_remain_available_as_local_commands() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "ci-gates:" in makefile
    assert "release-smoke:" in makefile
    assert "release-preflight:" in makefile
    assert "materialize-memorial-public-gold" in makefile
    assert "materialize-memorial-operator-status" in makefile
    assert "verify-whole-project-gold-map" in makefile
