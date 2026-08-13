#!/usr/bin/env python3
"""Run the bounded weekly vexp LTD missed-opportunity query pack."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/VEXP_LTD_OPPORTUNITY_INDEX.generated.json"
QUERIES = (
    "Find Black Ledger docs with no bounded media provider mapping",
    "Find release receipt producers with no Teable projection",
    "Find support surfaces suitable for bounded Emailit transport",
    "Find Foundry handoffs lacking approved FlipLink or MarkupGo artifacts",
    "Find campaign-memory surfaces suitable for approved Unmixr audio",
    "Find documented provider lanes absent from LTDs or governance LANES",
    "Find generated receipts whose source revision differs from current HEAD",
    "Find Tier 1 or Tier 2 LTDs lacking a fresh next-proof receipt",
    "Find runtime selectors naming providers with empty credentials",
    "Find routes lacking provider privacy approval and rollback proof",
    "Find public docs missing ClickRank freshness or crawl proof",
    "Find Teable projections without write-audit or freshness receipts",
    "Find provider promotions without a false-complete gate",
    "Find public artifacts that lack input and output hashes",
    "Find direct-send paths without named product ownership switches",
    "Find 1min background tasks without slot and credit receipts",
    "Find media candidates that can publish without human approval",
    "Find provider-facing operator labels that could expose private IDs",
    "Find parked LTDs referenced as live or production-ready",
    "Find external providers that appear to own product rules or release truth",
)


def _head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _run_query(query: str, *, timeout_seconds: int) -> dict[str, object]:
    try:
        completed = subprocess.run(
            ["vexp", "capsule", "--format", "json", "--max-tokens", "1200", query],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"query": query, "status": "blocked", "reason": type(exc).__name__}
    stdout = str(completed.stdout or "").strip()
    if completed.returncode != 0 or not stdout:
        return {
            "query": query,
            "status": "blocked",
            "reason": "vexp_query_failed",
            "exit_code": completed.returncode,
        }
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = {"text": stdout}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    summary = ""
    if isinstance(payload, dict):
        summary = str(payload.get("summary") or payload.get("answer") or "").strip()
    return {
        "query": query,
        "status": "candidate_requires_owner_review",
        "evidence_sha256": hashlib.sha256(encoded).hexdigest(),
        "evidence_bytes": len(encoded),
        "summary": " ".join(summary.split())[:500],
    }


def build_payload(*, execute: bool, timeout_seconds: int = 45) -> dict[str, object]:
    rows = (
        [_run_query(query, timeout_seconds=timeout_seconds) for query in QUERIES]
        if execute
        else [{"query": query, "status": "query_ready_not_executed"} for query in QUERIES]
    )
    succeeded = sum(1 for row in rows if row["status"] == "candidate_requires_owner_review")
    return {
        "contract": "ea.vexp_ltd_opportunity_index.v1",
        "status": (
            "projection_ready"
            if execute and succeeded == len(QUERIES)
            else "blocked_vexp_queries_incomplete"
            if execute
            else "query_pack_ready"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_commit_sha": _head(),
        "truth_posture": "candidate opportunities only; owner review required; no canon mutation",
        "query_count": len(QUERIES),
        "successful_query_count": succeeded,
        "opportunities": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = build_payload(execute=args.execute, timeout_seconds=max(5, args.timeout_seconds))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "query_count": payload["query_count"], "successful_query_count": payload["successful_query_count"], "output": str(output)}))
    return 0 if payload["status"] in {"projection_ready", "query_pack_ready"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

