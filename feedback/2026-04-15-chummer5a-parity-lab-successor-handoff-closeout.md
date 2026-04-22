Title: Chummer5a parity-lab successor handoff closeout

Package: next90-m103-ea-parity-lab

Owned surfaces: parity_lab:capture, veteran_compare_packs

What changed:
- Added `docs/chummer5a_parity_lab/SUCCESSOR_HANDOFF_CLOSEOUT.yaml` so future successor-wave shards have an explicit EA-scope completion artifact instead of rediscovering the same parity-lab pack.
- Tightened `tests/test_chummer5a_parity_lab_pack.py` to fail closed if the handoff closeout loses completed outputs, proof command/result, anti-reopen rules, or the non-EA ownership boundary for remaining milestone 103 work.
- Updated `docs/chummer5a_parity_lab/README.md` to point at the closeout handoff.

Proof:
- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=12 failed=0`

Remaining:
- No EA-owned parity-lab extraction work remains for `next90-m103-ea-parity-lab`.
- Promoted-head screenshot-backed veteran certification remains delegated to `next90-m103-ui-veteran-certification`.
