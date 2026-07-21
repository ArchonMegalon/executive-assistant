# Governed Spatial Render Canonical Re-review Handoff

Date: 2026-07-11 (Europe/Vienna)

Controller state: independent design re-review authorized; implementation remains blocked.

## Purpose

Launch one fresh, independent, read-only Chummer design reviewer for the exact
hash-bound canonical amendment. This reviewer must challenge the full amendment,
not repeat the amendment worker's conclusions. It may decide only `ACCEPT` or
`REVISE` and must not implement, publish, call providers, consume quota, or mutate
any repository or live system.

This amendment defines a reusable provider-neutral spatial-render contract:

- PropertyQuarry uses the generic apartment-tour and continuous-walkthrough path.
- Chummer may later consume the same contract through its own boundary mapper for
  style variants and a separate private fictional encounter-preview recipe.
- Public RUNSITE remains spatial orientation only. It does not become a combat,
  tactical, VTT, or live-mechanics surface.
- The encounter recipe consumes immutable mechanics and outcome references. It
  cannot calculate or mutate mechanics and is never PropertyQuarry input.

## Reviewer Isolation

1. Start a brand-new Codex session rooted at
   `/docker/chummercomplete/chummer-design`.
2. Do not resume session `019f4fbc-a589-7183-aaa6-6cae506f9c36` or any amendment
   worker.
3. Do not use `ea-3`; it is read-only for the spatial lane and is not the reviewer.
4. Obey the repository `AGENTS.md` and call vexp `run_pipeline` first. If vexp
   returns unrelated pivots, record the index mismatch once and use only targeted
   reads of the exact files named by the packet.
5. Use a read-only sandbox and make zero repository writes. Capture the final
   output only at
   `/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_INDEPENDENT_REVIEW.final.md`.
6. Return the fresh reviewer session ID, decision, final receipt SHA-256, and zero
   action counters to the EA controller pane.

## Frozen Candidate

| Artifact | SHA-256 | Filesystem mode |
| --- | --- | --- |
| `products/chummer/GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` | `cf5438fa5b18f07fb5a0321f9eb718f2bf61352b3a002d42dd210e2a86272753` | `0664` |
| `products/chummer/review/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_PACKET.md` | `83d0f49159f5218a3aadc2969f3ca3e4f3e2ac889a0f1bf4995954fc186e894c` | `0664` |

The packet binds 17 non-packet canonical files. Recompute all 17 hashes. Verify
that replacing the new schema hash
`cf5438fa5b18f07fb5a0321f9eb718f2bf61352b3a002d42dd210e2a86272753`
with the old schema hash
`132e5d4fe867298ea11509b4b367b6f4ab634c107371da0c87f5e087c727527f`
reconstructs the exact prior packet hash
`7b8ac07678f587444939416791043ea2ab89d38480ab90dd7eacfc8d70ca879e`.
No other packet byte may differ.

## Governing Evidence

Rehash these read-only inputs:

| Evidence | Required SHA-256 |
| --- | --- |
| `products/chummer/review/GOVERNED_SPATIAL_RENDER_PETITION_DECISION.md` | `2a5e4888bf2e9074a93e97e83d682e385eff53dd9c5ef8961fdc2fec6c2d1d6c` |
| `/docker/EA/EA_GOVERNED_SPATIAL_RENDER_DESIGN_PETITION.md` | `ed4f8452d59760e11b6ab7784c9a35d272db4d62520d6c742740573424b3f45e` |
| `/docker/EA/PROPERTYQUARRY_CHUMMER_GOVERNED_SPATIAL_RENDER_HANDOFF.md` | `e6ceebaedf91ef50a9e6179ac8775bbdb684147ffe1ca3ccc72175abcf68ee06` |
| `/docker/EA/_completion/governed-spatial-render/GOVERNED_SPATIAL_RENDER_DESIGN_REVIEW_RECEIPT.generated.json` | `3226895f1946d519bf5be62e9795b81bd3985de383f8efa6113c4fa4a05deb2c` |
| `/docker/property/PROPERTYQUARRY_GOVERNED_SPATIAL_RENDER_AUTHORITY_DECISION.md` | `401fe42211e2d8283ea9ca2a7cfc1a1eaffc80ff13c63fdf9e6158a116eff50a` |

Stop with `REVISE` if any frozen or governing hash differs.

## Required Review

Review all 18 amendment files for:

- ownership contradictions or dependency inversion;
- a source copy or canonical `ea.*` alias of the Chummer media contract;
- public RUNSITE combat, tactical, VTT, or live-mechanics leakage;
- PropertyQuarry authority overreach or private encounter fields crossing into it;
- coupling that makes the walkthrough require combat fields;
- incomplete numeric privacy, retention, deletion, legal-hold, takedown, backup,
  restoration, or closeout policy;
- fail-open authorization, quota state, evidence, idempotency, revocation, or
  readiness projection;
- promotion, publication, or readiness based on prose rather than executable
  evidence;
- additional material defects not already enumerated by the controller.

Confirm the exact external PropertyQuarry owners remain records, not Chummer
assignments:

- product bridge: repo `/docker/property`, package `app.product`, module
  `app.product.property_tour_hosting`;
- privacy lifecycle, intake, and closeout: repo `/docker/property`, package
  `app.api.routes`, module `app.api.routes.landing`;
- enforcement dependency: `public_tour_payloads`;
- revocation and deletion execution: `property_tour_hosting`.

PropertyQuarry implementation remains blocked pending its own numeric product
policy and independent re-review.

## Mandatory Executable Matrix

Use duplicate-key-safe YAML loading, `Draft202012Validator.check_schema`, and an
explicit offset-aware RFC 3339 format checker because the local optional default
date-time checker may be absent.

Coherent positive fixtures must include:

- `audit_only`;
- generic pre-execution `blocked`;
- `authorization_verified`;
- `reservation_held`;
- `released`;
- `attempt_committed`;
- `charge_pending`;
- `cancelled_reconciliation_pending`;
- `consumed`;
- `closed_consumed`;
- `compensation_pending`;
- `compensated`;
- `compensation_failed_blocked`.

Structural negative fixtures must include:

- `authorization.state=valid` with null refs, timestamps, quota digest, and zero
  maximum attempts while top posture is blocked;
- `not_present_audit_only` with populated authorization fields;
- `authorization_verified` carrying reservation, attempt, mutation, consumption,
  or compensation lineage;
- `released` carrying an attempt or later receipts;
- generic `blocked` carrying execution lineage;
- `audit_only` carrying a quota snapshot;
- every early, attempted, consumed, and compensated state-family mismatch;
- `build_allowed` with each of the three idempotency digests set to null;
- verified capability with rollback-only evidence;
- `build_allowed` with rollback-only evidence;
- `build_allowed` missing each of `provider_capability`,
  `canonical_compose_validator_exact_version`, `quota_snapshot`, and
  `kill_switch`.

Semantic negative fixtures must include:

- `quota.attempt_number` greater than
  `authorization.maximum_provider_attempts`, while explicitly acknowledging that
  Draft 2020-12 cannot compare sibling instance values;
- reversed or excessive capability timestamps;
- stale quota, kill-switch, authorization, compose-validator, browser, and canary
  evidence;
- reservation leases above the numeric maximum;
- resolved evidence with the wrong artifact family, environment, provider-route
  digest, gate version, digest, signature, revocation epoch, or idempotency scope.

Also run:

- `python3 scripts/ai/validate_contract_sets.py`;
- `python3 scripts/ai/validate_sync_manifest.py`, accepting exit 1 only if its
  output is exactly the unchanged eight missing horizon sources and their 64
  known mirror-expansion diagnostics, with no governed-spatial error;
- `git diff --check`;
- exact 17-entry packet hash verification;
- the five governing evidence hashes;
- a phrase-level scan showing zero obsolete PropertyQuarry authority, owner, or
  missing-decision claims.

## Decision Contract

The final receipt must begin with exactly one decision: `ACCEPT` or `REVISE`.

It must include:

- exact schema and packet hashes;
- fresh reviewer session ID;
- findings ordered by severity;
- positive, structural-negative, and semantic-negative test counts;
- all validator and baseline results;
- residual risks;
- zero-action counters;
- receipt SHA-256 after output capture.

`ACCEPT` means only that this exact design amendment is acceptable for a
separately authorized, bounded implementation-design phase. It does not authorize
runtime code, provider or account calls, quota reservation or consumption,
uploads, builds, browser runs, canaries, deployment, promotion, mirror
publication, PropertyQuarry implementation, Telegram, readiness projection, or
live mutation.

`REVISE` must identify exact blocking files, clauses, and failed fixtures.

Stop after the decision. Do not launch an amendment worker or implementation.
