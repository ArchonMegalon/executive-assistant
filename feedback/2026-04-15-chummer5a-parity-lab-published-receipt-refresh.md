Title: Chummer5a parity-lab published receipt refresh

Package: next90-m103-ea-parity-lab
Milestone: 103
Owned surfaces: parity_lab:capture, veteran_compare_packs

Shipped:
- Refreshed `.codex-studio/published/CHUMMER5A_PARITY_ORACLE_PACK.generated.json` from stale `preview_only` posture to `task_proven` so the published EA proof receipt matches the completed parity-lab docs.
- Tightened `tests/test_chummer5a_parity_lab_pack.py` to fail closed if the published receipt loses package id, milestone id, owned surfaces, completed output truth, no-blocker posture, or the delegated promoted-head certification boundary.
- Updated `docs/chummer5a_parity_lab/SUCCESSOR_HANDOFF_CLOSEOUT.yaml` and the README so future successor-wave shards see the published receipt as part of the EA closeout surface.

Proof:
- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=13 failed=0`

Remaining:
- No EA-owned parity-lab extraction work remains for `next90-m103-ea-parity-lab`.
- Promoted-head screenshot-backed veteran certification remains delegated to `next90-m103-ui-veteran-certification`.
