# Next90 M143 EA route-specific compare packs

Implemented the EA-owned M143 proof packet for the two direct-parity families:

- `sheet_export_print_viewer_and_exchange`
- `sr6_supplements_designers_and_house_rules`

What landed:

- `scripts/materialize_next90_m143_ea_route_specific_compare_packs.py` now compiles a route-specific compare-pack packet from the live EA compare-pack contract, Fleet veteran workflow pack, Fleet M143 closeout gate, screenshot review markers, dialog parity, rule-studio proof, and the deterministic core receipts doc.
- The generated packet now also imports the published `desktop_client` readiness lane from `/docker/fleet/.codex-studio/published/FLAGSHIP_PRODUCT_READINESS.generated.json` so each M143 family reflects the live desktop proof posture instead of implying route-local parity is enough to close flagship proof.
- The generated packet now fail-closes on canonical metadata drift across the design queue, Fleet queue, and successor registry, and it records the Fleet M143 gate pass state explicitly so reopened upstream closeout regressions break the EA proof packet instead of remaining a nominal pass.
- `scripts/verify_next90_m143_ea_route_specific_compare_packs.py` now fail-closes the generated packet if the family rows drift, route-local receipt tokens disappear, or the package metadata stops matching the canonical M143 EA row.
- `tests/test_next90_m143_ea_route_specific_compare_packs.py` now asserts the queue-alignment and Fleet gate monitors directly, so regenerated proof cannot silently drop those protections.
- `docs/chummer5a_parity_lab/NEXT90_M143_ROUTE_SPECIFIC_COMPARE_PACKS.generated.yaml` and `.md` are the reproducible package outputs for this slice.

Intentional boundary:

- This packet compiles and verifies the EA-owned compare/proof surface only.
- It does not claim canonical M143 closeout while the queue and registry rows remain unclosed upstream, even when the published readiness artifact reports `desktop_client = ready`.
