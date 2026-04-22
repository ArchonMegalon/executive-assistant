#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
DEFAULT_OUTPUT = Path(".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json")
SOURCE_BACKED_CASES = [
    "test_workspace_pages_render_seeded_product_objects",
    "test_browser_journey_updates_after_approval_and_commitment_closure",
    "test_browser_action_routes_match_rendered_forms",
    "test_browser_handoff_and_people_memory_actions_work",
]
REAL_BROWSER_CASES = [
    "test_activation_and_memo_flow_in_real_browser",
    "test_draft_and_commitment_workflows_in_real_browser",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_python_bin(root: Path) -> str:
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python.as_posix()
    return sys.executable


def _with_pythonpath(existing: str, root: Path) -> str:
    entries = [item for item in existing.split(os.pathsep) if item]
    for candidate in ("ea", (root / "ea").as_posix()):
        if candidate not in entries:
            entries.insert(0, candidate)
    return os.pathsep.join(entries)


def _case_expr(cases: list[str]) -> str:
    return " or ".join(cases)


def _truncate_output(text: str, *, limit: int = 40) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return lines[:limit]


def _extract_limitations(text: str) -> list[str]:
    lowered = text.lower()
    limitations: list[str] = []
    if "no module named 'uvicorn'" in lowered or 'no module named "uvicorn"' in lowered:
        limitations.append("uvicorn is not installed in the selected Python environment")
    if "no module named 'playwright'" in lowered or 'no module named "playwright"' in lowered:
        limitations.append("playwright is not installed in the selected Python environment")
    if "executable doesn't exist" in lowered or "browser_type.launch" in lowered:
        limitations.append("playwright browser binaries are not installed")
    if "skipped" in lowered and not limitations:
        limitations.append("real browser E2E did not run to completion")
    return limitations


def _run_pytest_cases(
    root: Path,
    *,
    python_bin: str,
    test_file: str,
    cases: list[str],
    real_browser: bool,
) -> dict[str, Any]:
    cmd = [
        python_bin,
        "-m",
        "pytest",
        "-q",
        test_file,
        "-k",
        _case_expr(cases),
    ]
    if real_browser:
        cmd.append("-rs")
    env = os.environ.copy()
    env["PYTHONPATH"] = _with_pythonpath(str(env.get("PYTHONPATH") or ""), root)
    started = time.monotonic()
    result = subprocess.run(
        cmd,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    duration_seconds = round(time.monotonic() - started, 3)
    combined_output = "\n".join(
        part for part in (str(result.stdout or "").strip(), str(result.stderr or "").strip()) if part
    )
    limitations = _extract_limitations(combined_output)
    if result.returncode == 0:
        status = "pass"
    elif real_browser and "skipped" in combined_output.lower():
        status = "preview_only"
    else:
        status = "blocked"
    return {
        "status": status,
        "command": shlex.join(cmd),
        "cwd": root.as_posix(),
        "python_bin": python_bin,
        "test_file": test_file,
        "cases": cases,
        "exit_code": result.returncode,
        "duration_seconds": duration_seconds,
        "output_excerpt": _truncate_output(combined_output),
        "limitations": limitations,
    }


def build_receipt(
    root: Path,
    *,
    seed_path: Path = DEFAULT_SEED,
    runner: Callable[..., dict[str, Any]] = _run_pytest_cases,
) -> dict[str, Any]:
    seed = _load_json(root / seed_path)
    python_bin = _resolve_python_bin(root)
    source_backed = runner(
        root,
        python_bin=python_bin,
        test_file="tests/test_product_browser_journeys.py",
        cases=SOURCE_BACKED_CASES,
        real_browser=False,
    )
    real_browser = runner(
        root,
        python_bin=python_bin,
        test_file="tests/e2e/test_product_workflows.py",
        cases=REAL_BROWSER_CASES,
        real_browser=True,
    )

    blocking_reasons: list[str] = []
    current_limitations: list[str] = []
    if source_backed["status"] != "pass":
        blocking_reasons.append("source-backed browser journey proof is not passing")
        current_limitations.extend(source_backed.get("limitations") or [])
    if real_browser["status"] == "blocked":
        blocking_reasons.append("real browser E2E proof is not passing")
        current_limitations.extend(real_browser.get("limitations") or [])
    elif real_browser["status"] == "preview_only":
        current_limitations.extend(real_browser.get("limitations") or [])

    if not blocking_reasons and real_browser["status"] == "pass":
        status = "pass"
        operator_summary = "EA browser workflow proof is published and green across both seeded browser journeys and real-browser E2E."
    elif not blocking_reasons:
        status = "preview_only"
        operator_summary = "EA browser workflow proof is published, but it remains preview_only until the real-browser E2E slice runs cleanly."
    else:
        status = "blocked"
        operator_summary = "EA browser workflow proof is published, but it is blocked by failing or unavailable proof lanes."

    receipt = {
        "contract_name": "ea.browser_workflow_proof",
        "product": str(seed.get("product") or "executive-assistant"),
        "surface": "browser_workflow_proof",
        "version": 1,
        "kind": "proof_receipt",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_ea_browser_workflow_proof.py",
        "status": status,
        "operator_summary": operator_summary,
        "seed_source": seed_path.as_posix(),
        "release_claim_summary": str((seed.get("release_claim") or {}).get("summary") or "").strip(),
        "expected_browser_signals": list((seed.get("browser_workflow_proof") or {}).get("expected_browser_signals") or []),
        "source_backed_journey_proof": source_backed,
        "real_browser_e2e_proof": real_browser,
        "blocking_reasons": blocking_reasons,
        "current_limitations": sorted(set(current_limitations)),
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the EA browser workflow proof receipt.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="EA repository root.")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="EA flagship release seed.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to write the generated receipt.")
    parser.add_argument("--stdout", action="store_true", help="Print the receipt JSON to stdout.")
    args = parser.parse_args()

    root = args.root.resolve()
    receipt = build_receipt(root, seed_path=args.seed)
    output_path = root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.stdout:
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "output": output_path.as_posix(), "receipt_status": receipt["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
