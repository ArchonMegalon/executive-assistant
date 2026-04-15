Title: Chummer5a parity-lab direct proof runner

Date: 2026-04-15
Owner: executive-assistant
Package: next90-m103-ea-parity-lab
Milestone: 103
Owned surfaces: parity_lab:capture, veteran_compare_packs

What shipped:
- Tightened `tests/test_chummer5a_parity_lab_pack.py` so the package manifest must remain `task_proven`.
- Added a direct Python runner to the focused parity-lab test file so the package can be proven in EA worker runtimes where `pytest` is not installed.
- Documented the direct verification command in `docs/chummer5a_parity_lab/README.md`.

Verification:
- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=10 failed=0`
- `python -m pytest -q tests/test_chummer5a_parity_lab_pack.py` remains blocked because `pytest` is not installed in this EA runtime.

What remains:
- No EA-owned parity-lab extraction work remains for `next90-m103-ea-parity-lab`.
- Downstream promoted-head veteran certification remains in `next90-m103-ui-veteran-certification`.

Exact blocker:
- None for the EA-owned package scope.
