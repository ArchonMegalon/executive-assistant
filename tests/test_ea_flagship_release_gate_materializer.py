from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_ea_flagship_release_gate.py"
OUTPUT = Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json")
SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
TRUTH_PLANE = Path(".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md")
BROWSER_PROOF = Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json")
PRODUCT_CANON_DOCS = [
    Path(".codex-design/ea/README.md"),
    Path(".codex-design/ea/START_HERE.md"),
    Path(".codex-design/ea/VISION.md"),
    Path(".codex-design/ea/PUBLIC_NAVIGATION.yaml"),
    Path(".codex-design/ea/APP_NAVIGATION.yaml"),
    Path(".codex-design/ea/SURFACE_DESIGN_SYSTEM.md"),
    Path(".codex-design/ea/FIRST_VALUE_JOURNEY.md"),
    Path(".codex-design/ea/COPY_PRINCIPLES.md"),
    Path(".codex-design/ea/METRICS_AND_SLOS.yaml"),
    Path(".codex-design/ea/LTD_INTEGRATION_MAP.md"),
]


def _write_minimal_flagship_tree(
    root: Path,
    *,
    browser_proof_status: str | None = None,
) -> None:
    (root / SEED).parent.mkdir(parents=True, exist_ok=True)
    (root / TRUTH_PLANE).parent.mkdir(parents=True, exist_ok=True)
    (root / OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    (root / BROWSER_PROOF).parent.mkdir(parents=True, exist_ok=True)
    for rel in PRODUCT_CANON_DOCS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("# canon\n", encoding="utf-8")

    seed = {
        "product": "executive-assistant",
        "surface": "flagship_release_control",
        "version": 1,
        "truth_plane": {
            "source": ".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md",
            "legacy_history": "MILESTONE.json",
        },
        "release_claim": {
            "summary": "EA can only claim flagship-grade release truth when the browser workflow proof and release asset verification agree with this gate seed.",
            "required_conditions": [
                "EA product canon exists and names the public navigation, app navigation, first-value journey, surface system, copy rules, and LTD delivery map",
                "browser workflow proof renders seeded browser workspace pages with durable product objects",
                "browser workflow proof shows browser actions updating the live workspace without stale narration",
                "real browser E2E covers activation and the memo-to-queue loop",
                "release asset verification knows the EA flagship truth plane and gate seed",
                "release checklists cite the EA truth plane instead of using MILESTONE green as the oracle",
            ],
        },
        "ea_product_canon": {
            "source_root": ".codex-design/ea",
            "required_docs": [path.as_posix() for path in PRODUCT_CANON_DOCS],
        },
        "browser_workflow_proof": {
            "evidence_sources": [
                {
                    "file": "tests/test_product_browser_journeys.py",
                    "cases": ["test_workspace_pages_render_seeded_product_objects"],
                },
                {
                    "file": "tests/e2e/test_product_workflows.py",
                    "cases": ["test_activation_and_memo_flow_in_real_browser"],
                },
            ]
        },
        "verification_binding": {
            "primary_verifier": "scripts/verify_release_assets.sh",
            "supporting_test": "tests/test_flagship_truth_plane.py",
        },
    }
    (root / SEED).write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    (root / TRUTH_PLANE).write_text("# EA flagship truth plane\n", encoding="utf-8")
    for rel in ("README.md", "RUNBOOK.md", "RELEASE_CHECKLIST.md", "PRODUCT_RELEASE_CHECKLIST.md"):
        (root / rel).write_text(
            "\n".join(
                [
                    "EA_FLAGSHIP_TRUTH_PLANE.md",
                    "EA_FLAGSHIP_RELEASE_GATE.json",
                    "EA_FLAGSHIP_RELEASE_GATE.generated.json",
                    "scripts/materialize_ea_flagship_release_gate.py",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    for rel in ("tests/test_product_browser_journeys.py", "tests/e2e/test_product_workflows.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("# browser proof source\n", encoding="utf-8")
    if browser_proof_status is not None:
        (root / BROWSER_PROOF).write_text(
            json.dumps({"status": browser_proof_status, "browser_workflow_proof": True}, indent=2) + "\n",
            encoding="utf-8",
        )


def test_materializer_writes_preview_only_receipt_without_browser_execution_receipt(tmp_path: Path) -> None:
    _write_minimal_flagship_tree(tmp_path)

    subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--seed",
            SEED.as_posix(),
            "--truth-plane",
            TRUTH_PLANE.as_posix(),
            "--output",
            OUTPUT.as_posix(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    receipt = json.loads((tmp_path / OUTPUT).read_text(encoding="utf-8"))

    assert receipt["product"] == "executive-assistant"
    assert receipt["surface"] == "flagship_release_control"
    assert receipt["version"] == 1
    assert receipt["status"] == "preview_only"
    assert receipt["truth_plane"]["source"] == ".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md"
    assert receipt["ea_product_canon"]["source_root"] == ".codex-design/ea"
    assert receipt["ea_product_canon"]["all_required_docs_present"] is True
    assert receipt["browser_workflow_proof"]["published_receipt_present"] is False
    assert receipt["browser_workflow_proof"]["source_files_present"][0]["present"] is True
    assert receipt["browser_workflow_proof"]["source_files_present"][1]["present"] is True
    assert "no published browser execution receipt is attached yet" in receipt["current_limitations"]
    assert receipt["blocking_reasons"] == []
    assert "preview_only" in receipt["operator_summary"]


def test_materializer_can_publish_pass_when_browser_execution_receipt_exists(tmp_path: Path) -> None:
    _write_minimal_flagship_tree(tmp_path, browser_proof_status="pass")

    subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--seed",
            SEED.as_posix(),
            "--truth-plane",
            TRUTH_PLANE.as_posix(),
            "--output",
            OUTPUT.as_posix(),
            "--browser-proof-receipt",
            BROWSER_PROOF.as_posix(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    receipt = json.loads((tmp_path / OUTPUT).read_text(encoding="utf-8"))

    assert receipt["status"] == "pass"
    assert receipt["browser_workflow_proof"]["published_receipt_present"] is True
    assert receipt["browser_workflow_proof"]["published_receipt"] == BROWSER_PROOF.as_posix()
    assert receipt["current_limitations"] == []
    assert receipt["blocking_reasons"] == []
    assert receipt["ea_product_canon"]["all_required_docs_present"] is True
    assert "green" in receipt["operator_summary"]


def test_materializer_surfaces_browser_proof_blockers_when_published_receipt_is_blocked(tmp_path: Path) -> None:
    _write_minimal_flagship_tree(tmp_path)
    (tmp_path / BROWSER_PROOF).write_text(
        json.dumps(
            {
                "status": "blocked",
                "blocking_reasons": [
                    "source-backed browser journey proof is not passing",
                    "real browser E2E proof is not passing",
                ],
                "current_limitations": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--seed",
            SEED.as_posix(),
            "--truth-plane",
            TRUTH_PLANE.as_posix(),
            "--output",
            OUTPUT.as_posix(),
            "--browser-proof-receipt",
            BROWSER_PROOF.as_posix(),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    receipt = json.loads((tmp_path / OUTPUT).read_text(encoding="utf-8"))

    assert receipt["status"] == "blocked"
    assert "browser workflow proof: source-backed browser journey proof is not passing" in receipt["blocking_reasons"]
    assert "browser workflow proof: real browser E2E proof is not passing" in receipt["blocking_reasons"]
