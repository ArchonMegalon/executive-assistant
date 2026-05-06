# Next90 M142 EA family-local screenshot and interaction packs

Refreshed the EA-owned M142 receipt so it matches the current direct-parity proof state instead of preserving the earlier blocked narrative.

The packet is pinned to canonical queue frontier `5399660048`, the live readiness posture is `desktop_client = ready`, and duplicate queue or registry rows fail closed across the design queue, Fleet queue, and .codex-design local mirror as well as the successor registry task.

What landed:

- `scripts/materialize_next90_m142_ea_family_local_screenshot_and_interaction_packs.py` now emits a richer family-local markdown packet that keeps screenshot receipts and interaction receipts separate for each workflow family instead of collapsing the proof into broad family prose.
- The markdown packet now renders explicit `screenshot receipts` and `interaction receipts` group lines inside every workflow family so a future shard cannot flatten the proof back into one undifferentiated list.
- The markdown packet now also exposes the route-local receipt tokens behind each screenshot and interaction proof, so reviewers can see the exact `source_key` plus required proof markers without opening the YAML.
- The materializer now also binds the packet to the approved `.codex-design` local mirror and preserves `generated_at` when the semantic proof payload is unchanged, so repeat verification does not create timestamp-only churn.
- The generated packet keeps `dense_builder_and_career_workflows`, `dice_initiative_and_table_utilities`, and `identity_contacts_lifestyles_history` explicit, with each family listing its compare artifacts, workflow task ids, required screenshots, parity posture, screenshot receipts, and interaction receipts.
- `scripts/verify_next90_m142_ea_family_local_screenshot_and_interaction_packs.py` now requires the feedback receipt to pin the current desktop readiness posture and the screenshot-versus-interaction split, so stale blocker copy cannot drift back in after the package is already passing.
- The verifier and unit tests now fail closed if the repo-local mirror row, mirrored registry task, or mirror-to-canonical fingerprints drift for this package.
- `docs/chummer5a_parity_lab/NEXT90_M142_FAMILY_LOCAL_SCREENSHOT_AND_INTERACTION_PACKS.generated.yaml` and `.md` remain the reproducible package outputs for this slice.

Intentional boundary:

- This packet compiles and verifies the EA-owned compare/proof surface only.
- It does not mark the canonical queue or registry rows complete locally while the design queue and Fleet queue still report `not_started` and the registry task row remains unclosed upstream.
- The packet is currently passing for all three families, but that pass is proof packaging, not local authority to close milestone `142.4`.
