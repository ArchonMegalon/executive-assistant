# Governed Spatial Render Canonical Revision 2 Handoff

Date: 2026-07-11 (Europe/Vienna)

Controller status: independent content review returned `REVISE`; implementation
remains blocked.

## Bound Review Decision

Independent reviewer session:
`019f5020-a15e-7eb0-a8fd-908875302cfd`

Decision receipt:
`/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_INDEPENDENT_REVIEW.final.md`

Receipt SHA-256:
`1155ab9c64d897c0f7d1795c92978cfb0d1b45cecc59f480a8baf5abf2b7d25b`

The review covered all 18 amendment files and passed the prescribed matrix:

- duplicate-key-safe YAML: 6/6;
- Draft 2020-12 metaschema: pass;
- offset-aware RFC 3339 checker: 5/5;
- lifecycle positives: 13/13;
- required structural negatives: 87/87;
- required semantic negatives: 41/41;
- packet manifest: 17/17;
- contract validator: pass;
- sync baseline: exactly 8 sources and 64 diagnostics, no spatial diagnostic;
- stale PropertyQuarry authority wording: zero;
- literal canonical EA alias: zero.

The reviewer added two adversarial fixtures. Both were unexpectedly accepted and
are P1 blockers:

1. A receipt with `signature.algorithm: none`, an attacker-controlled key ref,
   and no signature value is structurally valid. The schema has no approved
   algorithm constraint, signature/MAC bytes or detached-signature reference, or
   exact canonical signed-payload definition.
2. A fully executed `compensation_failed_blocked` receipt can set the original
   build key, normalized-request digest, and composition digest to null because
   non-null idempotency is gated only by the current top-level
   `quota_posture: build_allowed`. This loses replay and compensation lineage
   after posture changes to blocked.

No implementation, provider, quota, build, live, mirror, or readiness action is
authorized by this handoff.

## Worker Identity And Scope

Resume the existing canonical amendment worker session only:
`019f4fbc-a589-7183-aaa6-6cae506f9c36`.

Do not create a replacement amendment worker. Do not use `ea-3`.

Frozen inputs before this revision:

| File | SHA-256 | Mode |
| --- | --- | --- |
| `products/chummer/GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` | `cf5438fa5b18f07fb5a0321f9eb718f2bf61352b3a002d42dd210e2a86272753` | `0664` |
| `products/chummer/review/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_PACKET.md` | `83d0f49159f5218a3aadc2969f3ca3e4f3e2ac889a0f1bf4995954fc186e894c` | `0664` |

The only content-write scope is those two files. Preserve every other dirty byte,
all modes, all 16 other packet hashes, and all external repositories.

The worker must stop at `proposed_for_independent_re_review`. It may not launch
the next review.

## Required Signature Contract

Replace the non-verifiable free-form signature shape with one exact,
cryptographically verifiable profile. The conservative v1 profile is Ed25519:

- `algorithm`: exact constant `ed25519`;
- `encoding`: exact constant `base64url_no_padding`;
- `signature_value`: required base64url without padding, exactly 86 characters,
  representing a 64-byte Ed25519 signature;
- `key_ref`: required non-empty opaque signing-key reference;
- `key_epoch`: required non-negative integer;
- `canonicalization`: exact constant `rfc8785_jcs`;
- `signed_payload_scope`: exact constant
  `entire_receipt_excluding_signature`;
- `signed_payload_digest`: required SHA-256 digest.

The canonical semantic contract must state exactly:

1. Remove the top-level `signature` member from the receipt.
2. Canonicalize the remaining JSON value according to RFC 8785 JCS. Receipt
   producers must not use non-finite numbers; this schema currently uses no
   floating-point fields.
3. SHA-256 the canonical UTF-8 bytes and require exact equality with
   `signed_payload_digest`.
4. Decode `signature_value` as unpadded base64url and require exactly 64 bytes.
5. Resolve `key_ref` and `key_epoch` to an active Ed25519 public key owned by the
   declared issuer for the exact environment.
6. Reject an unknown, mismatched, revoked, not-yet-valid, or expired key. The
   top-level receipt expiry must not exceed signing-key expiry.
7. Verify the Ed25519 signature over the same RFC 8785 canonical bytes.
8. Any canonicalization, digest, key, epoch, algorithm, encoding, scope, or
   signature mismatch fails closed to `unverified_or_blocked`.

Do not add a second ambiguous signature mode, optional `none` algorithm, generic
free-form algorithm, unsigned fallback, provider signature shape, or prose-only
verification claim.

Add executable in-memory fixtures that:

- generate a deterministic Ed25519 keypair and valid signature;
- structurally accept the coherent signature profile;
- semantically verify the valid signature;
- reject `algorithm: none` structurally;
- reject missing, empty, malformed, padded, short, or long signature values;
- reject wrong encoding, canonicalization, payload scope, digest, key ref, key
  epoch, issuer, environment, revoked key, expired key, tampered payload, and
  cryptographic signature mismatch.

Use the installed `cryptography` Ed25519 API if available. Tests must not write
keys or fixtures to disk. If no suitable cryptographic verifier exists, stop and
report a blocker instead of simulating a pass.

## Required Build-Lineage Contract

Idempotency and original authorization bindings are lifecycle lineage, not a
permission implied by current posture. They must survive route blocking,
capability revocation, authorization expiry/revocation, cancellation,
compensation, and compensation failure.

Add a required nullable field to the base idempotency object:
`authorization_binding_digest`.

Define one structural build-lineage idempotency shape requiring non-null:

- `scope_digest`;
- `key_digest`;
- `normalized_request_digest`;
- `composition_digest`;
- `authorization_binding_digest`.

The semantic contract must define `authorization_binding_digest` as SHA-256 of
the canonical immutable authorization binding containing owner,
`authorization_ref`, authorization `issued_at`, authorization `expires_at`,
`maximum_provider_attempts`, and `quota_limit_digest`.

Apply the non-null build-lineage shape based on `quota.state`, independently of
current `quota_posture`, `capability_state`, revocation, or kill-switch state, to
every build lifecycle state:

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

For those states, require an immutable original authorization lineage shape with
non-null `authorization_ref`, issue and expiry timestamps, positive bounded
maximum attempts, and quota-limit digest. Current authorization state may be
`valid`, `expired`, `revoked`, or `blocked`, but its original binding fields may
not disappear after execution. `not_present_audit_only` remains valid only for
the zero-burn audit path.

Generic `quota.state: blocked` remains strictly pre-execution and may not carry
build execution lineage. `audit_only` remains outside the build state machine.

Add structural fixtures that set each build-lineage field to null independently
for every listed state, with special fixtures for
`compensation_failed_blocked`, revoked capability, expired authorization,
revoked authorization, and an engaged kill switch. Every malformed fixture must
reject. Add coherent positive fixtures for the same blocked/revoked terminal
conditions with all immutable lineage retained.

Add semantic fixtures that reject:

- `authorization_binding_digest` not matching the immutable authorization;
- idempotency scope, key, request, or composition digest changed after the first
  reservation or attempt;
- the same key with a different request/composition/authorization binding;
- a compensation or retry bound to a different original authorization;
- duplicate compensation, optimistic refund, or attempt outside the original
  authorization maximum.

## Packet Revision

Update the packet to describe the exact Ed25519/JCS signature profile, immutable
build-lineage/idempotency rule, and new negative fixtures. Do not overclaim that
design tests are runtime implementation evidence.

After schema bytes freeze:

1. update the packet's one schema hash row;
2. preserve all other 16 embedded hashes;
3. compute the new packet SHA-256 with self-hash excluded as before;
4. preserve schema and packet mode `0664`;
5. bind this review receipt and decision in the worker's final receipt, but do
   not add it as an unapproved canonical file or modify any other packet-bound
   file.

## Full Regression Matrix

Rerun every prior check plus the new fixtures:

- duplicate-key-safe YAML parsing;
- `Draft202012Validator.check_schema`;
- explicit offset-aware RFC 3339 checker;
- all 13 lifecycle positives;
- all 87 prior structural negatives;
- all 41 prior semantic negatives;
- signature positive and all signature negatives above;
- every build-state lineage null/mutation negative above;
- all 18 cross-file ownership, recipe, RUNSITE, privacy, milestone, mirror, and
  PropertyQuarry assertions;
- `python3 scripts/ai/validate_contract_sets.py`;
- exact known sync baseline classifier;
- `git diff --check`;
- zero stale PropertyQuarry authority claims;
- all 17 embedded packet hashes and five governing evidence hashes;
- exact before/after forbidden-repository fingerprints.

EA remains `CONCURRENT EXTERNAL DRIFT`; never claim it is unchanged. Prove this
worker made no EA write from its action log. PropertyQuarry, run-services, and
hub-registry must remain exact against the controller baselines.

## Authorized Telegram Milestone

Before resuming the amendment worker, EA may send exactly one concise Telegram
milestone to the existing operator destination:

> PropertyQuarry 3D-tour design review: REVISE. Two P1 contract issues were
> caught before implementation: signed receipts are not yet cryptographically
> verifiable, and blocked executed jobs can lose idempotency lineage. No
> provider, quota, build, or live work ran. EA is correcting the two-file schema
> packet, then another independent review is required. Full flagship launch ETA
> remains unproven until design acceptance and the implementation, browser,
> video, and canary gates pass.

Record only the Telegram delivery receipt. Do not send videos, artifacts, or a
second update in this revision.

## Hard Stop

No runtime code, implementation-repo schema, route, adapter, API, provider call,
account call, upload, quota reservation/consumption, build, browser run, video,
canary, deployment, promotion, mirror publication, PropertyQuarry mutation,
readiness projection, or live mutation.

Return exact changed files and hashes, full fixture counts, validation results,
Telegram delivery receipt, zero-action counters, concurrent-drift truth, and
remaining blocked gates. Status ceiling remains
`proposed_for_independent_re_review`.
