from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _make_target_body(target: str) -> str:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    marker = f"{target}:\n"
    assert marker in makefile
    tail = makefile.split(marker, maxsplit=1)[1]
    body: list[str] = []
    for line in tail.splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


def test_manfred_source_gate_covers_launch_critical_contracts() -> None:
    body = _make_target_body("verify-manfred-memorial-source-gate")

    required_suites = {
        "tests/test_manfred_memorial_deployment_contract.py",
        "tests/test_manfred_spatial_candidate_browser.py",
        "tests/test_manfred_joint_deploy.py",
        "tests/test_memorial_governed_deploy.py",
        "tests/test_memorial_private_context.py",
        "tests/test_memorial_security_contracts.py",
        "tests/test_memorial_release_policy.py",
        "tests/test_public_tour_release_policy.py",
        "tests/test_propertyquarry_public_tour_branding.py",
        "tests/test_public_tour_publication_quarantine.py",
        "tests/test_public_tour_no_media_renderer.py",
        "tests/test_memorial_spatial_tour_public_origin.py",
        "tests/test_ea_public_ingress_reconciliation.py",
        "tests/test_memorial_gold_readiness.py",
        "tests/test_memorial_operator_artifacts.py",
        "tests/test_memorial_source_gate_contract.py",
        "tests/test_github_actions_budget_policy.py",
        "tests/test_project_mode_manifests.py",
        "tests/test_release_materialization_service.py",
        "tests/test_whole_project_gold_map.py",
        "tests/test_memorial_live_conversation_contracts.py",
        "tests/test_providers_api_contracts.py",
        "ea/tests/test_memorial_runtime.py",
    }

    for suite in required_suites:
        assert suite in body
    assert "-k 'public_memorial or public_tour'" in body
    assert "--rootdir=ea ea/tests/test_memorial_runtime.py" in body


def test_manfred_source_gate_cannot_mutate_or_contact_live_runtime() -> None:
    body = _make_target_body("verify-manfred-memorial-source-gate").lower()

    for forbidden in (
        "docker",
        "systemctl",
        "deploy-ea",
        "reconcile-ea-public-ingress",
        "http://",
        "https://",
    ):
        assert forbidden not in body


def test_manfred_promotion_preflight_sequences_source_and_joint_proof_only() -> None:
    body = _make_target_body("verify-manfred-memorial-promotion-preflight")

    source_index = body.index("$(MAKE) verify-manfred-memorial-source-gate")
    joint_index = body.index("$(MAKE) verify-ea-memorial-joint-deploy")
    assert source_index < joint_index
    assert "$(MAKE) deploy-ea-memorial" not in body
    assert "reconcile-ea-public-ingress" not in body


def test_manfred_public_launch_gate_materializes_every_public_proof_plane() -> None:
    body = _make_target_body("manfred-memorial-public-launch-gates")

    expected = (
        "$(MAKE) verify-ea-public-ingress-public",
        "$(MAKE) materialize-memorial-public-gold",
        "$(MAKE) memorial-gold-gates",
        "$(MAKE) materialize-memorial-operator-status",
    )
    positions = [body.index(command) for command in expected]
    assert positions == sorted(positions)
    assert "$(MAKE) deploy-ea-memorial" not in body


def test_joint_operator_docs_bind_candidate_permit_and_public_evidence() -> None:
    joint = (ROOT / "docs/MANFRED_MEMORIAL_JOINT_DEPLOY_RUNBOOK.md").read_text(
        encoding="utf-8"
    )
    ingress = (
        ROOT / "docs/EA_PUBLIC_INGRESS_RECONCILIATION_RUNBOOK.md"
    ).read_text(encoding="utf-8")

    assert '--spatial-browser-receipt "$EA_MEMORIAL_SPATIAL_BROWSER_RECEIPT"' in joint
    assert "--permit-mode joint" in joint
    assert "make verify-manfred-memorial-promotion-preflight" in joint
    assert "make deploy-ea-memorial" in joint
    assert "make manfred-memorial-public-launch-gates" in joint
    assert "~/.ea-memorial-deploy-state/joint-active-recovery.json" in joint
    assert "Treat this journal as secret-bearing" in joint
    assert "has no command-line or environment override" in joint
    assert "A retained journal or cleanup error" in joint
    assert "cannot clear a" in joint
    assert "committed cleanup incident" in joint
    assert "They cannot authorize a new materialization" in joint
    assert "scripts/deploy_ea_memorial_joint.py" in ingress
    assert "A future coordinator" not in ingress
