#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
DEFAULT_TRUTH_PLANE = Path(".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md")
DEFAULT_OUTPUT = Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json")
DEFAULT_BROWSER_PROOF_RECEIPT = Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json")
REQUIRED_DOCS = (
    Path("README.md"),
    Path("RUNBOOK.md"),
    Path("RELEASE_CHECKLIST.md"),
    Path("PRODUCT_RELEASE_CHECKLIST.md"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _present(root: Path, rel: Path) -> bool:
    return (root / rel).exists()


def _stringify_path(path: Path) -> str:
    return path.as_posix()


def _build_browser_sources(root: Path, seed: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    evidence_sources = list((seed.get("browser_workflow_proof") or {}).get("evidence_sources") or [])
    rendered: list[dict[str, Any]] = []
    missing: list[str] = []
    for entry in evidence_sources:
        rel = Path(str(entry.get("file") or "").strip())
        cases = [str(case) for case in list(entry.get("cases") or []) if str(case).strip()]
        present = _present(root, rel)
        rendered.append(
            {
                "file": rel.as_posix(),
                "present": present,
                "cases": cases,
            }
        )
        if not present:
            missing.append(rel.as_posix())
    return rendered, missing


def _build_doc_checks(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rendered: list[dict[str, Any]] = []
    missing: list[str] = []
    for rel in REQUIRED_DOCS:
        present = _present(root, rel)
        rendered.append({"path": rel.as_posix(), "present": present})
        if not present:
            missing.append(rel.as_posix())
    return rendered, missing


def build_receipt(
    root: Path,
    *,
    seed_path: Path = DEFAULT_SEED,
    truth_plane_path: Path = DEFAULT_TRUTH_PLANE,
    browser_proof_receipt_path: Path | None = DEFAULT_BROWSER_PROOF_RECEIPT,
) -> dict[str, Any]:
    seed = _load_json(root / seed_path)
    truth_plane_present = _present(root, truth_plane_path)
    docs, missing_docs = _build_doc_checks(root)
    browser_sources, missing_browser_sources = _build_browser_sources(root, seed)

    published_browser_receipt = None
    browser_receipt_status = None
    browser_receipt_path_value = None
    if browser_proof_receipt_path is not None:
        candidate = root / browser_proof_receipt_path
        browser_receipt_path_value = browser_proof_receipt_path.as_posix()
        if candidate.exists():
            published_browser_receipt = _load_json(candidate)
            browser_receipt_status = str(
                published_browser_receipt.get("status")
                or published_browser_receipt.get("state")
                or published_browser_receipt.get("release_truth")
                or ""
            ).strip()
        elif truth_plane_present:
            browser_receipt_status = None

    blockers: list[str] = []
    current_limitations: list[str] = []
    if not truth_plane_present:
        blockers.append(f"missing truth plane: {truth_plane_path.as_posix()}")
    if missing_docs:
        blockers.append("missing release docs: " + ", ".join(missing_docs))
    if missing_browser_sources:
        blockers.append("missing browser proof sources: " + ", ".join(missing_browser_sources))
    if published_browser_receipt is None:
        current_limitations.append("no published browser execution receipt is attached yet")

    status = "blocked" if blockers else "preview_only"
    if published_browser_receipt is not None:
        if browser_receipt_status in {"pass", "preview_only", "blocked", "fail"}:
            status = "pass" if browser_receipt_status == "pass" and not blockers else "blocked" if browser_receipt_status == "fail" else browser_receipt_status
        else:
            status = "preview_only" if not blockers else "blocked"

    release_summary = str((seed.get("release_claim") or {}).get("summary") or "").strip()
    if status == "pass":
        operator_summary = "EA flagship release truth is published as a machine-readable receipt and currently green."
    elif status == "preview_only":
        operator_summary = "EA flagship release truth is materialized as a machine-readable receipt, but the current claim is preview_only until browser execution proof is published."
    else:
        operator_summary = "EA flagship release truth is materialized, but it is blocked by missing proof or docs."

    receipt: dict[str, Any] = {
        "product": str(seed.get("product") or "executive-assistant"),
        "surface": str(seed.get("surface") or "flagship_release_control"),
        "version": int(seed.get("version") or 1),
        "kind": "release_receipt",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_ea_flagship_release_gate.py",
        "status": status,
        "operator_summary": operator_summary,
        "truth_plane": {
            "source": truth_plane_path.as_posix(),
            "present": truth_plane_present,
            "legacy_history": (seed.get("truth_plane") or {}).get("legacy_history"),
        },
        "release_claim": seed.get("release_claim") or {},
        "browser_workflow_proof": {
            "evidence_sources": seed.get("browser_workflow_proof", {}).get("evidence_sources", []),
            "source_files_present": browser_sources,
            "published_receipt": browser_receipt_path_value,
            "published_receipt_present": published_browser_receipt is not None,
        },
        "verification_binding": {
            "primary_verifier": (seed.get("verification_binding") or {}).get("primary_verifier", "scripts/verify_release_assets.sh"),
            "supporting_test": (seed.get("verification_binding") or {}).get("supporting_test", "tests/test_flagship_truth_plane.py"),
            "materializer": "scripts/materialize_ea_flagship_release_gate.py",
        },
        "documentation_refs": [
            {"path": rel.as_posix(), "present": present}
            for rel, present in (
                (Path("README.md"), _present(root, Path("README.md"))),
                (Path("RUNBOOK.md"), _present(root, Path("RUNBOOK.md"))),
                (Path("RELEASE_CHECKLIST.md"), _present(root, Path("RELEASE_CHECKLIST.md"))),
                (Path("PRODUCT_RELEASE_CHECKLIST.md"), _present(root, Path("PRODUCT_RELEASE_CHECKLIST.md"))),
            )
        ],
        "release_docs": docs,
        "blocking_reasons": blockers,
        "current_limitations": current_limitations,
        "release_truth": {
            "oracle": truth_plane_path.as_posix(),
            "seed": seed_path.as_posix(),
            "summary": release_summary,
        },
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the EA flagship release receipt.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="EA repository root.")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="Path to the EA flagship release seed.")
    parser.add_argument("--truth-plane", type=Path, default=DEFAULT_TRUTH_PLANE, help="Path to the EA flagship truth plane.")
    parser.add_argument(
        "--browser-proof-receipt",
        type=Path,
        default=DEFAULT_BROWSER_PROOF_RECEIPT,
        help="Optional browser execution receipt to fold into the current status.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to write the generated receipt.")
    parser.add_argument("--stdout", action="store_true", help="Print the receipt to stdout instead of writing only to disk.")
    args = parser.parse_args()

    receipt = build_receipt(
        args.root.resolve(),
        seed_path=args.seed,
        truth_plane_path=args.truth_plane,
        browser_proof_receipt_path=args.browser_proof_receipt,
    )

    output_path = args.root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.stdout:
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "output": output_path.as_posix(), "receipt_status": receipt["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
