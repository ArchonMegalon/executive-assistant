from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "README.md",
    "RUNBOOK.md",
    "ENVIRONMENT_MATRIX.md",
    ".codex-design/ea/USER_FIRST_AUDIT_2026-06-18.md",
    "docs/chummer_closure_coverage/CHUMMER_CLOSURE_COVERAGE_PACK.yaml",
    "docs/chummer_closure_coverage/README.md",
    "docs/chummer_closure_coverage/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
    "docs/preference_profiles/README.md",
    "scripts/materialize_next90_m135_ea_closure_coverage.py",
    "scripts/verify_next90_m113_operator_safe_packets.py",
    "scripts/verify_next90_m118_ea_organizer_packets.py",
    "scripts/verify_next90_m135_ea_closure_coverage.py",
    "ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py",
)
EA_LOCAL_PROOF_FILES = (
    "docs/chummer_governor_packets/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
    "docs/chummer_explain_narration_packs/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
    "docs/chummer_launch_followthrough/CHUMMER_LAUNCH_FOLLOWTHROUGH_PACK.yaml",
    "docs/chummer_launch_followthrough/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
    "docs/chummer_operator_safe_packets/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
    "docs/chummer_organizer_packets/CHUMMER_ORGANIZER_PACKET_PACK.yaml",
    "docs/chummer_organizer_packets/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
)


def _rendered() -> str:
    return "\n".join((ROOT / name).read_text(encoding="utf-8") for name in FILES)


def test_docs_and_verifiers_do_not_embed_old_workspace_roots() -> None:
    rendered = _rendered()

    assert "/docker/" + "EA/" not in rendered
    assert "/docker/" + "fleet" not in rendered
    assert "/docker/" + "property" not in rendered
    assert "/docker/" + "chummercomplete" not in rendered
    assert "/mnt/" + "pcloud" not in rendered


def test_verifier_expected_paths_are_derived_from_repo_root() -> None:
    rendered = _rendered()

    assert "_repo_path(" in rendered
    assert "Path(__file__).resolve().parents" in rendered
    assert "(ROOT / entry).as_posix()" in rendered
    assert "relative_to(repo_root)" in rendered


def test_ea_local_packet_proof_lists_do_not_embed_host_repo_root() -> None:
    rendered = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in EA_LOCAL_PROOF_FILES)

    assert "/docker/" + "EA/" not in rendered
