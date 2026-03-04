# EA Execution Backlog

Last updated: 2026-03-04
Branch: `main`

## Definition Of Done (DoD)
- All backlog items are marked `DONE` or `BLOCKED` with reason.
- Latest full gate pass exists from `bash scripts/docker_e2e.sh`.
- Working tree is clean (`git status --short` has no changes).
- Local commits are present (no push required).

## Current Milestone: v1.19.4 Consolidation
- [DONE] Capability registry baseline (`capability_registry.py` + smoke + gates).
- [DONE] Generic skill inventory baseline (`generic.py`, `registry.py`, `skill_inventory` smoke).
- [DONE] Capability planning router (`capability_router.py` + smoke + gates).
- [DONE] Human compose contract tightening and wording alignment.
- [DONE] Doc/code drift guard (`smoke_v1_19_4_doc_alignment.py` + gates).
- [DONE] Generic skill handlers return deterministic capability plan metadata.
- [DONE] Full Docker E2E gate pass after each slice.

## Blocked
- None.

## Next Queue (on new feedback)
- Integrate capability plan selection into runtime execution paths (beyond contract placeholders).
- Expand behavioral E2E coverage for sidecar/skill orchestration outcomes.
- Optional convergence of LLM gateway package/export paths while preserving existing contract smokes.
