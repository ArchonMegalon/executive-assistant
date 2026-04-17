Package: `next90-m103-ea-parity-lab`
Milestone: `103`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

Current implementation-only retry proof:

- Fixed the direct proof guard so the current retry prompt can be the authority when the active handoff stderr tail trims the initial implementation-only retry lines.
- Kept the change scoped to `tests/test_chummer5a_parity_lab_pack.py`; the frozen closeout receipt, generated parity oracle receipt, oracle baselines, veteran workflow pack, compare packs, and fixture inventory remain unchanged.
- Did not invoke operator telemetry, active-run helper commands, supervisor status or eta helpers, or Chummer5a oracle recapture.

Verification:

- `python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed
- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`

No EA-owned oracle extraction work remains for this package. Remaining M103 work stays delegated to the non-EA packages named in `SUCCESSOR_HANDOFF_CLOSEOUT.yaml`.
