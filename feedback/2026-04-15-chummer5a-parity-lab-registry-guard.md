Title: Chummer5a parity-lab registry guard

Package: next90-m103-ea-parity-lab
Milestone: 103
Owned surfaces: parity_lab:capture, veteran_compare_packs

What changed:
- Added `docs/chummer5a_parity_lab/README.md` so the EA parity-lab package has a stable local front door and explicit proof boundary.
- Tightened `tests/test_chummer5a_parity_lab_pack.py` to fail closed if the package manifest drifts from the canonical successor registry or queue staging entry.
- Kept the package scoped to EA-owned extraction evidence; promoted-head certification and host-proof ingestion remain delegated to their successor packages.

Verification:
- `python -m pytest tests/test_chummer5a_parity_lab_pack.py` could not run because `pytest` is not installed in the EA environment.
- Direct Python invocation of every `tests/test_chummer5a_parity_lab_pack.py::test_*` function passed with `ran=8 failed=0`.
