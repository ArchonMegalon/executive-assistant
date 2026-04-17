Package: `next90-m103-ea-parity-lab`
Milestone: `103`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

Implementation-only retry guard:

- Verified the current 2026-04-17 handoff and task-local telemetry with no operator telemetry, active-run helper commands, oracle recapture, or supervisor status or eta helpers.
- Tightened `tests/test_chummer5a_parity_lab_pack.py` so the current retry prompt must keep the implementation-only rule, exact first-command block, allowed-path inspection rule, explicit start-editing instruction, supervisor-helper ban, and stale historical-status-snippet handling.
- Added a guard that keeps the exact four-command startup block separate from the longer direct-read context list, so `NEXT_12_BIGGEST_WINS_REGISTRY.yaml` and `ACTIVE_RUN_HANDOFF.generated.md` remain follow-on reads rather than invented first commands.
- Added a guard for the worker stop-report contract so retry workers keep the restricted `What shipped`, `What remains`, and `Exact blocker` closeout shape after the writable-scope block.
- Added a guard that treats the active handoff stderr tail as worker-safe context only: a historical supervisor-polling warning must stay a do-not-repeat note, while stale-snippet handling, helper ban, and restricted stop-report shape remain anchored to the active prompt rather than closure evidence.
- Left the frozen closeout receipt, generated parity oracle receipt, oracle baselines, workflow pack, compare packs, and fixture inventory unchanged because the append conditions still do not fail.

Verification:

- `python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed
- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`

No EA-owned oracle recapture or receipt timestamp refresh was needed. Remaining M103 work stays with the non-EA packages named in `SUCCESSOR_HANDOFF_CLOSEOUT.yaml`.
