# Chummer5a Parity Lab Pack

Package: `next90-m103-ea-parity-lab`
Milestone: `103`
Owner: `executive-assistant`

This pack is the EA-owned extraction handoff for the successor-wave Chummer5a parity lab. It captures the source-backed oracle baseline inventory, first-minute veteran task map, compare artifacts, and import/export fixture inventory used by the downstream UI veteran-certification package.

Owned surfaces:

- `parity_lab:capture`
- `veteran_compare_packs`

Canonical outputs:

- `CHUMMER5A_PARITY_LAB_PACK.yaml` is the package manifest and successor-wave handoff.
- `oracle_baselines.yaml` records Chummer5a oracle counts, source-backed desktop landmarks, and screenshot corpus pointers.
- `veteran_workflow_pack.yaml` maps the required first-minute veteran landmarks and tasks.
- `compare_packs.yaml` maps every flagship parity family to extracted compare artifacts.
- `import_export_fixture_inventory.yaml` records the import/export fixture universe from the Chummer5a oracle.
- `SUCCESSOR_HANDOFF_CLOSEOUT.yaml` records that the EA-owned successor slice is complete and names the remaining non-EA followups.
- `.codex-studio/published/CHUMMER5A_PARITY_ORACLE_PACK.generated.json` is the published task-proven proof receipt for this EA package.

Proof boundary:

- This package extracts and normalizes oracle evidence only.
- Promoted-head visual review remains owned by `next90-m103-ui-veteran-certification`.
- Desktop host-proof ingestion and release promotion remain owned by the release/operator lanes; the current flagship readiness packet is green with zero unresolved external host-proof requests, so this pack must not reopen the closed flagship wave.
- `SUCCESSOR_HANDOFF_CLOSEOUT.yaml` carries repeat-prevention markers for successor frontier `4287684466`; future workers should treat the EA slice as closed while the canonical registry, queue staging packet, completed outputs, and proof command still agree.
- The closeout is also bound to the active run handoff focus for frontier `4287684466` and package `next90-m103-ea-parity-lab`, so a repeated worker should verify that evidence plus canonical registry and queue closure before moving on to delegated non-EA M103 work instead of recapturing EA artifacts.
- The active handoff timestamp guard is a minimum generated-at value, not an exact-value trap; a newer handoff stays valid, while an older handoff cannot be used to justify repeating the EA extraction work.

Verification:

- `python tests/test_chummer5a_parity_lab_pack.py` runs the parity-lab contract checks directly for worker runtimes where `pytest` is not installed.
