Title: Chummer5a parity-lab successor proof tightening

Package: next90-m103-ea-parity-lab
Milestone: 103
Owned surfaces: parity_lab:capture, veteran_compare_packs

What changed:
- Refreshed `docs/chummer5a_parity_lab/CHUMMER5A_PARITY_LAB_PACK.yaml` for the successor-wave package authority and current flagship readiness evidence.
- Removed the stale compare-pack host-proof blocker; current desktop readiness is now cited from `/docker/fleet/.codex-studio/published/FLAGSHIP_PRODUCT_READINESS.generated.json`.
- Split screenshot corpus truth into:
  - primary captured UI screenshots under `/docker/chummercomplete/chummer6-ui/.codex-studio/published/ui-flagship-release-gate-screenshots`
  - supplemental closed-flagship master-index and character-roster screenshots under `/docker/chummercomplete/chummer6-ui-finish/.codex-studio/published/ui-flagship-release-gate-screenshots`
- Tightened `tests/test_chummer5a_parity_lab_pack.py` so claimed screenshot files must exist on disk and cannot be repeated as supplemental proof.

Verification:
- Direct Python invocation of every `tests/test_chummer5a_parity_lab_pack.py::test_*` function passed.
- `python -m pytest tests/test_chummer5a_parity_lab_pack.py` could not run because `pytest` is not installed in the EA environment.

Remaining handoff:
- `next90-m103-ui-veteran-certification` still owns the promoted-head screenshot-backed veteran certification review.
- EA's parity-lab capture pack is source-backed and successor-handoff ready for this package scope.
