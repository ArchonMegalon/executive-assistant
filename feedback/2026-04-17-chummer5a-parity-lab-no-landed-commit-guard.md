Package: `next90-m103-ea-parity-lab`
Frontier: `4287684466`
Milestone: `103`

What changed:

- Tightened `tests/test_chummer5a_parity_lab_pack.py` so the canonical registry task row, design queue row, and Fleet queue row for the completed EA package must not grow a fresh `landed_commit` field.
- Kept closure anchored to the frozen proof receipt, direct proof command, and scoped proof anchors instead of a moving repository `HEAD`.

Proof:

- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`

Boundary:

No EA-owned parity-lab extraction work remains. This pass did not invoke operator telemetry, active-run helper commands, helper-output proof, Chummer5a oracle recapture, or flagship-wave reopening.
