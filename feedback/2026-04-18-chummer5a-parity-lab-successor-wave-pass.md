# next90-m103-ea-parity-lab successor-wave pass

What shipped:
- Extended the EA-owned parity-lab extraction docs with WinForms-backed veteran landmark normalization for Global Settings, Character Settings, Master Index, Character Roster, Hero Lab Importer, Data Exporter, and Export Character.
- Wired the new legacy-form anchors into `docs/chummer5a_parity_lab/oracle_baselines.yaml`, `docs/chummer5a_parity_lab/veteran_workflow_pack.yaml`, and `docs/chummer5a_parity_lab/compare_packs.yaml` so screenshot baselines, first-minute veteran tasks, and compare families now resolve to both web-oracle tokens and original desktop-form sources.
- Tightened `tests/test_chummer5a_parity_lab_pack.py` to fail closed on the new cross-source landmark coverage and reran `python3 -m py_compile tests/test_chummer5a_parity_lab_pack.py` plus `python3 tests/test_chummer5a_parity_lab_pack.py`.

What remains:
- No EA-owned parity-lab extraction work remains. Any further M103 work is non-EA follow-up in the already-complete UI veteran-certification slice or other downstream consumers.

Exact blocker:
- None inside the assigned EA package.
