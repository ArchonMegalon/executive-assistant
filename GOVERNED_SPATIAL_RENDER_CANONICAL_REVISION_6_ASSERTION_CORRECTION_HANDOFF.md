# Governed Spatial Render Canonical Revision 6 Assertion-Correction Handoff

Date: 2026-07-11 (Europe/Vienna)
Controller posture: same outer EA Codex, direct bounded assertion correction
Worker, helper, and reviewer delegation: forbidden
Maximum status: `proposed_for_independent_re_review`
Implementation, provider, quota, build, publication, promotion, and readiness authority: none

## Decision

Revision 5 completed its one permitted final harness at `339/341`. Both failures were harness assertion defects against hash-verified canonical files, not schema, state-machine, signature, or fixture failures. Revision 6 authorizes the same outer EA Codex to correct exactly those two predicates and run the otherwise byte-for-byte and case-for-case preserved consolidated harness once.

No worker, helper, subagent, collaborator, `ea-3`, or reviewer may be launched. Revision 6 does not supersede any canonical ownership, authority split, fail-closed rule, independent-review gate, implementation blocker, PropertyQuarry blocker, promotion blocker, or readiness blocker. It supersedes only the two erroneous R5 assertion predicates identified below.

## Bound Evidence

| Evidence | SHA-256 | Meaning |
| --- | --- | --- |
| `/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_5_CONTROLLER.final.md` | `816232856d60d073b845904fca153b09b14198b50fcd245fc1bf8909683dda1d` | Honest R5 `339/341` failure receipt and exact two-failure record |
| `/docker/EA/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_5_RECOVERY_HANDOFF.md` | `d84bb803522d921eb1b7fd81154cf0a5a8611f1d776f77f13f45056eab347704` | Preserved R5 harness, fixture, JCS, signature, matrix, command, parity, and authority contract |
| `/docker/EA/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_4_RECOVERY_HANDOFF.md` | `4524fe394454911f58bfda153155d8945f200d5485ad2f1b0afcfdc32cafc0bb` | Inherited recovery and full-matrix contract |
| `/docker/EA/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_3_HANDOFF.md` | `52f77bc7db4cf28b552523deefdabf92b5aabd9244914a04d2e8e1d0d733c5aa` | Inherited P1 correction and authority contract |
| `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_2_INDEPENDENT_REREVIEW.final.md` | `be2cf8b882ae2652fd5e81d22512e20731629f2ac81f80f20c0ba1d494856979` | Independent `REVISE` decision that still requires a fresh re-review after this checkpoint |

All governing evidence hashes bound by the canonical packet remain mandatory and exact.

## Frozen Canonical Bytes

The controller verified these bytes and modes before creating this handoff:

| File | Revision 6 starting SHA-256 | Mode | Revision 6 write authority |
| --- | --- | ---: | --- |
| `/docker/chummercomplete/chummer-design/products/chummer/GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` | `f86e6f737ba3333f7e84d8196481cda4c4cc34dc08d6b5aff5a7465af303546f` | `0664` | none; must remain byte-identical |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_PACKET.md` | `c7e9e01c7f12020e9a4e1898cd3d1fcc6250a02b60449519a8fc13bf138cef4c` | `0664` | conditional packet-only update after an exact `341/341` result |

All other Chummer files and modes are read only. Preserve all existing dirty work. No reset, clean, checkout, stash, revert, overwrite, formatting sweep, generator, or bulk rewrite is authorized.

## Exact Assertion Corrections

Correct exactly these two predicates in the in-memory R5 harness. The file content used by each predicate is lowercased before comparison.

1. `cross_file_assertion:milestone_pending_blocked`
   - Require lowercase `PROGRAM_MILESTONES.yaml` to contain literal `spatial-render` and literal `blocked`.
   - Do not require `governed-spatial`.

2. `cross_file_assertion:sync_manifest_paths`
   - Require lowercase `sync-manifest.yaml` to contain `governed_spatial_render_capability_quota_evidence.schema.yaml`.
   - Require it to contain `governed_spatial_render_privacy_retention_policy.md`.
   - Require it not to contain `governed_spatial_render_canonical_amendment_packet.md`; the review packet path is not a sync-manifest requirement.

These are assertion-harness corrections only. They authorize no canonical schema edit, sync-manifest edit, milestone edit, privacy-policy edit, packet edit before the harness, or semantic reinterpretation.

## Preserved R5 Harness Contract

Except for the two predicates above, preserve every R5 harness implementation detail, fixture, mutation, expected count, rejection layer, supported-domain JCS rule, cryptographic construction, command boundary, repository predicate, and output contract unchanged.

In particular:

- run exactly one final consolidated harness through Python standard input with `PYTHONDONTWRITEBYTECODE=1`;
- create no repository or `/tmp` harness, script, fixture, key, cache, bytecode, report, or generated artifact;
- make no package install, tool update, network call, provider call, or account/quota lookup;
- retain the recursive duplicate-safe bounded no-float JSON contract and safe-integer bounds;
- retain UTF-16BE object-key ordering via `key.encode('utf-16-be')` and compact `ensure_ascii=False` scalar serialization;
- retain known ordering/escaping vectors and local `node -e` `JSON.stringify` parity for the supported domain only;
- retain deterministic real Ed25519 and deep-copy deletion of exactly `signature_value` and `signed_payload_digest`;
- retain all structural, semantic, chronology, freshness, key-registry, state-lineage, cross-file, manifest, validator, sync-baseline, boundary, owned-file, and protected-repository cases;
- retain the exact R5 group denominators and total denominator `341`;
- retain the exact R5 command boundary and protected-repository predicates.

The only expected tally change is `cross_file_assertion` from `16/18` to `18/18`, producing total `341/341`. Prior R3 and R4 harness counts remain invalid. R5 remains an honest failed run and is not retroactively relabeled.

## One-Run Gate

Run the corrected consolidated harness once and only once.

If the result is not exactly `341/341`:

- do not add or promote packet result claims;
- do not update the packet for an R6 binding;
- record every exact failing case and stop;
- do not rerun, repair, delegate, or launch review.

If the result is exactly `341/341`:

- use `apply_patch` to update only the canonical amendment packet;
- add this R6 handoff path and SHA-256 as governing evidence;
- record the truthful reproduced group table and exact `341/341` count;
- retain all 17 existing canonical manifest rows and hashes byte-for-byte, including schema SHA-256 `f86e6f737ba3333f7e84d8196481cda4c4cc34dc08d6b5aff5a7465af303546f`;
- bind direct outer-controller execution, zero delegated workers, and the exact R6 assertion corrections;
- keep status only `proposed_for_independent_re_review` and state that fresh independent review remains required.

After a green result, run only small independent controller checks: hashes, modes, packet manifest/governing-row parsing, all manifest and governing hashes, repository fingerprints, `git diff --check`, contract-set validator, known sync classifier, stale-authority/alias boundary checks, and action-log reconciliation. Do not reconstruct or rerun the full harness.

## Authority And Forbidden Actions

EA remains provider-redacted derived telemetry and separately authorized synthetic zero-burn compose assistance only. Media-factory owns Chummer contract/execution receipts and quota mutation. Hub owns the Chummer bridge. Registry owns publication/revocation. Fleet owns landing evidence. PropertyQuarry retains its separately bound exact owners and remains blocked pending its numeric product policy and independent re-review.

Required count `0`:

- schema content writes;
- canonical content writes outside the conditional packet-only update;
- worker, helper, subagent, collaborator, `ea-3`, or reviewer launches;
- PropertyQuarry writes;
- runtime or implementation writes;
- provider/account/network/balance/credential/quota calls;
- upload, provider job, reservation, consumption, cancellation, compensation, build, or test build;
- browser, video, tour, FPS, accessibility, or canary actions;
- deployment, mirror/public publication, promotion, or readiness projection;
- Telegram or other notification.

Telegram message `3772` was already sent by this controller at `2026-07-11T10:45:12Z`. It is historical binding only. Revision 6 sends no Telegram or other notification.

## Repository Parity

PropertyQuarry, `/docker/chummercomplete/chummer.run-services`, and `/docker/chummercomplete/chummer-hub-registry` must retain exact pre-action HEAD/raw/cached/status fingerprints. Chummer may differ only by the conditional packet edit and must retain the exact schema bytes. EA is concurrent external/controller drift and must not be called unchanged; account for this handoff through the direct action log and use repository fingerprints as evidence, not ownership of unrelated drift.

## Final Controller Receipt

Write the bounded result to:

`/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_6_CONTROLLER.final.md`

The receipt must include this handoff hash, R5 receipt binding, starting and final canonical hashes/modes, the exact one-run matrix, manifest and governing evidence checks, repository parity, action log, Telegram historical binding, forbidden counters, and remaining gates. It must state that no independent reviewer was launched and that the receipt is not implementation, provider, quota, build, publication, promotion, launch, or readiness evidence.

Stop at `proposed_for_independent_re_review`. Do not launch the reviewer and do not authorize implementation.
