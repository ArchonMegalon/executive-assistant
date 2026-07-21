# Governed Spatial Render Canonical Revision 4 Recovery Handoff

Date: 2026-07-11 (Europe/Vienna)
Controller posture: outer controller only
Revision 2 independent decision: `REVISE`
Revision 3 outcome: exhausted worker / invalid verification evidence
Worker status ceiling: `proposed_for_independent_re_review`
Implementation, runtime, provider, quota, build, publication, and readiness authority: none

## Recovery purpose

Revision 3 did not produce a trustworthy final receipt. Preserve the current schema and packet bytes as the Revision 4 starting point, but do not freeze, accept, or repeat any Revision 3 harness count or packet verification claim.

This handoff authorizes exactly one fresh `debug_hard` recovery worker. It supersedes only the Revision 3 requirement to resume worker `019f4fbc-a589-7183-aaa6-6cae506f9c36`, because that worker's context is exhausted. Every other authority boundary, forbidden action, source-of-truth rule, design gate, and independent-review requirement from Revision 3 remains in force.

The exhausted worker must never be resumed again. Do not launch `ea-3`, a helper, a subagent, a collaborator, or a reviewer.

## Bound evidence

Read these files in full before changing either owned file:

| Evidence | Required SHA-256 | Meaning |
| --- | --- | --- |
| `/docker/EA/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_3_HANDOFF.md` | `52f77bc7db4cf28b552523deefdabf92b5aabd9244914a04d2e8e1d0d733c5aa` | Complete Revision 3 contract; inherited except for the exhausted-worker identity restriction and invalid R3 results |
| `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_2_INDEPENDENT_REREVIEW.final.md` | `be2cf8b882ae2652fd5e81d22512e20731629f2ac81f80f20c0ba1d494856979` | Independent `REVISE` decision from reviewer session `019f506f-9596-7892-a551-b0481cc95760` |
| `/home/tibor/.codex/sessions/2026/07/11/rollout-2026-07-11T07-53-11-019f4fbc-a589-7183-aaa6-6cae506f9c36.jsonl` | `c768b301330e928b4db402a8e742d33f840dabfa9c8d788a6239361f22aeb81d` | Exhausted Revision 3 worker transcript and action evidence; read only and targeted inspection only |

The complete authority/evidence hashes bound by Revision 3 remain exact, including the governing petition decision, PropertyQuarry authority decision, EA petition, generated design-review receipt, cross-project handoff, Revision 2 correction handoff, Revision 2 worker receipt, and Revision 2 independent re-review.

## Revision 4 starting bytes

These bytes are preserved, not accepted. They are the only repository files the recovery worker may change.

| File | Starting SHA-256 | Mode | Size |
| --- | --- | ---: | ---: |
| `/docker/chummercomplete/chummer-design/products/chummer/GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` | `724c03079c41c0f0c2ea94fb89057cafe200bb7ea014cf422f7d9c5526ff2a30` | `0664` | 46816 bytes |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_PACKET.md` | `68dcad9f5a6fd89b53a6a2f95dcd3222f001c2a5864b6cbe2fb4f1194d81210b` | `0664` | 33983 bytes |

All other Chummer files and modes are read only. Preserve all pre-existing dirty work. Do not reset, clean, checkout, stash, revert, overwrite, reformat, or normalize unrelated content.

## Invalid Revision 3 evidence

Every Revision 3 harness count is invalid. The amendment packet currently contains unverified claims left by the exhausted worker; they are not frozen evidence and must be replaced or removed unless reproduced by the one clean Revision 4 harness.

The controller observed and records these exact process failures:

1. Repeated invalid fixture baselines produced false positive and false negative counts, including malformed digests, incoherent state fixtures, reversed `run_case` expectations, and totals that did not match the constructed cases.
2. Repeated syntax and quoting errors prevented clean harness execution.
3. The worker created `/tmp/validate_rev3.py` despite the explicit no-fixture instruction. Before controller deletion it was mode `0600`, size 50293 bytes, SHA-256 `169a30570953424d77992193dd3eb6fdb7abd73bcd4a68a58295a21bad751960`.
4. The worker performed broad `rg` and `/tmp` exploration instead of the bounded, supplied-context workflow.
5. The worker directly rewrote Python harness content outside `apply_patch`.
6. The worker used ordinary `json.dumps(..., sort_keys=True)` and mislabeled it as RFC 8785 JCS. Python code-point ordering and Python number serialization do not prove RFC 8785 UTF-16 property ordering or ECMAScript number serialization.
7. The worker's signature construction replaced excluded members with empty strings instead of deleting exactly `signature.signature_value` and `signature.signed_payload_digest` before canonicalization.
8. The final worker process failed with a context overflow: `Codex ran out of room in the model's context window. Start a new thread or clear earlier history before retrying.` No Revision 3 final receipt was produced.

The controller captures the failed artifact hash above, removes `/tmp/validate_rev3.py`, and does not preserve it as a validator or fixture. The transcript remains read-only failure evidence. Do not recreate that file or any replacement fixture file.

## Worker identity and contract

Launch exactly one fresh CodexEA `debug_hard` worker. The wrapper must record the new actual worker session identity in the final receipt. The worker may not resume, fork, or impersonate any earlier worker or reviewer session.

The only repository content-write scope is the two files in `Revision 4 starting bytes`. Repository edits must use `apply_patch`. No direct Python, shell redirection, formatter, generator, or bulk rewrite may write repository content.

Read-only context is limited to:

- this Revision 4 recovery handoff;
- the complete Revision 3 handoff;
- the Revision 2 independent `REVISE` receipt;
- the two owned files;
- the 16 other canonical files in the packet's 17-file manifest;
- the exact governing evidence files named by Revision 3;
- repository-local AGENTS/design-mirror instructions and existing validators required by Revision 3;
- targeted portions of the exhausted transcript only when needed to substantiate the failure/action log.

Do not use broad repository search. The controller supplies the relevant paths and hashes. If `vexp run_pipeline` fails only because the installed client requires an update, record that exact failure once, do not install or update anything, and proceed with targeted reads.

## Required content result

Re-evaluate all four Revision 2 P1 findings against the preserved starting bytes. Correct the schema and packet only where required, without weakening any existing lineage, authorization, capability, evidence-family, quota, kill-switch, privacy, ownership, or promotion boundary.

The final contract must prove:

1. The signed payload deep-copies the complete duplicate-safe parsed receipt and deletes exactly `signature.signature_value` and `signature.signed_payload_digest`; every key/profile selector remains signed.
2. Key identity, fingerprint uniqueness, global revocation, no alias reactivation, no epoch reuse, and exact `key.not_before <= receipt.issued_at <= receipt.expires_at <= key.not_after` chronology fail closed.
3. Raw UTF-8 JSON rejects duplicate names before value construction, BOM, malformed UTF-8, unpaired surrogates, non-finite values, unsafe integers, and unsupported numeric values before canonicalization.
4. RFC 8785 behavior uses UTF-16 code-unit property ordering and ECMAScript number serialization. Ordinary Python `sort_keys` is not acceptable evidence.
5. Generic pre-execution `quota.state: blocked` keeps only correlation scope and nulls all build idempotency and quota lineage.
6. `compensation_failed_blocked` remains a build-lifecycle terminal under blocked top posture and a blocked/engaged route, while retaining the complete original idempotency, authorization, reservation, attempt, mutation, consumption, and compensation lineage required by its immutable execution history.
7. `compensation_failed_blocked` is never accepted as `build_allowed`, never confused with generic `quota.state: blocked`, and never loses its original authorization binding when capability, authorization, revocation, quota posture, or kill switch blocks later execution.
8. No schema or packet wording projects implementation, provider capability, artifact readiness, promotion, publication, or launch readiness.

## One clean no-file harness

Run exactly one final consolidated validation harness after the two owned files reach their intended bytes. The harness must be supplied through process standard input or an equivalent in-memory command. It must not create a repository file, `/tmp` file, cache, bytecode, key, report, fixture, or generated artifact. Use `PYTHONDONTWRITEBYTECODE=1` for Python. Do not install packages or use network access.

Preflight snippets used only to inspect installed local libraries are allowed, but no intermediate or iterative validation count may be reported as evidence. Only the single final consolidated run may populate the packet and receipt counts. If that run fails, patch the owned files as needed and run one new final consolidated harness; explicitly discard the failed run and never combine counts across runs.

The harness must use a real standards path:

- UTF-16 code-unit object-key ordering, including non-BMP keys;
- ECMAScript-compatible JSON number serialization, including the RFC 8785 number vector;
- RFC 8785 string escaping and invalid-Unicode rejection;
- safe integer bounds `-9007199254740991..9007199254740991` wherever integers are admitted;
- real Ed25519 using the installed `cryptography` implementation or the local Node `crypto` implementation;
- canonical unpadded base64url decoding to exactly 64 signature bytes;
- actual deletion, not blanking, of the two excluded signature members.

An acceptable no-install implementation is an in-memory JavaScript canonicalizer that recursively sorts object keys with native JavaScript UTF-16 ordering and serializes accepted scalar values with `JSON.stringify`, combined with explicit pre-canonicalization rejection and known RFC 8785 vectors. A Python-only `sort_keys=True` substitute is forbidden.

## Full regression matrix

The one clean run must emit a named case table and exact tally for every group. Preserve the full Revision 3 matrix and at minimum prove:

- duplicate-key-safe YAML `6/6`;
- Draft 2020-12 schema validity with `FormatChecker`;
- raw JSON valid-boundary positives and negatives for duplicate names, BOM, invalid UTF-8, unpaired surrogates, non-finite numbers, unsafe integers, and trailing data;
- RFC 8785 known Unicode/escaping, UTF-16 key-order, ECMAScript number, safe-integer-boundary, and non-finite/unsafe-number vectors;
- deterministic real Ed25519 positive and a non-ASCII/JCS positive;
- signature structural negatives, semantic/cryptographic negatives, and signed-envelope mutation negatives for algorithm, encoding, key ref, key epoch, fingerprint, canonicalization, scope, digest, signature, issuer, environment, expiry, and payload tampering;
- same-key alias, duplicate fingerprint, global revocation, no-reactivation, epoch reuse/backward movement, unknown key, and key chronology negatives;
- all 11 build-state positives `11/11`;
- per-state idempotency null negatives `55/55`;
- per-state original-authorization null/zero negatives `55/55`;
- coherent blocked/revoked/expired build-terminal positives `6/6`, including exact `compensation_failed_blocked` blocked-posture lineage;
- all compensation-failed lineage-loss negatives, named individually;
- generic blocked smuggling `8/8` structurally rejected and `8/8` semantically rejected: each of four build idempotency fields alone, all four together, reservation lineage, attempt plus mutation lineage, and consumption plus compensation lineage;
- audit-only positive;
- authorization-binding arithmetic, request/composition mutation, same-key conflict, concurrent duplicate, retry, compensation, duplicate-compensation, optimistic-refund, and attempt-limit negatives;
- offset-aware RFC 3339 chronology, freshness, expiry, authorization age, reservation lease, evidence age, and no-validity-skew tests;
- all 18 cross-file ownership, recipe, RUNSITE, privacy, milestone, mirror, and PropertyQuarry assertions;
- packet manifest `17/17`, exact hashes for the other 16 files, and the final schema hash in the packet;
- all governing evidence hashes exact;
- `python3 scripts/ai/validate_contract_sets.py` output `ok`;
- `git diff --check` success;
- stale PropertyQuarry unresolved-authority contradictions `0`;
- literal canonical `ea.*` Chummer contract aliases `0`;
- known sync classifier only: exit `1`, 8 unchanged missing sources, 56 expansions, 64 diagnostics, zero governed-spatial diagnostics;
- before/after protected-repository fingerprints and zero writes outside the two owned files.

Every negative must prove that the intended validator layer rejected the intended defect. A fixture that fails for an unrelated malformed field does not count. Record the primary rejection path for each named case.

## Manifest and packet rules

The packet is a proposal for independent re-review, not a self-acceptance artifact.

- Replace every stale or unverified Revision 3 count with the exact one-clean-run result.
- Do not retain a claim merely because it appeared in the starting packet.
- Update the schema row to the final schema SHA-256.
- Preserve exact hashes for the other 16 manifest files.
- Do not add the packet itself to its self-referential manifest.
- Record this Revision 4 handoff hash, the exhausted-worker failure status, and the fresh worker identity.
- State explicitly that Revision 3 produced no valid receipt and that its harness evidence was discarded.
- Keep status exactly `proposed_for_independent_re_review`.

## Authority and forbidden actions

EA remains derived-telemetry/compose-only and is not Chummer canon authority. Media-factory owns Chummer contract/execution receipts. Hub owns the Chummer bridge. Registry and Fleet retain their accepted boundaries. PropertyQuarry retains its exact external owners and remains blocked pending its numeric product policy and independent re-review.

MagicFit, OMagic, Matterport, 3DVista, and every other provider or hosted-tour capability remain unverified for this lane. No prose, schema, test fixture, historical receipt, or design decision grants provider, quota, build, publication, promotion, or readiness authority.

Forbidden actions, each required final count `0`:

- runtime or implementation code changes;
- any repository write outside the two owned Chummer files;
- PropertyQuarry or EA content mutation by the worker;
- provider, account, network, balance, credential, or quota lookup;
- provider job, upload, reservation, consumption, cancellation, compensation, build, or test build;
- browser, video, tour, spatial render, FPS, accessibility run, or canary;
- deployment, mirror publication, public publication, promotion, or readiness projection;
- Telegram or any other notification;
- package install, tool update, helper, subagent, reviewer, or additional worker launch.

The prior controller Telegram decision update was already sent as message `3769` at `2026-07-11T09:32:50Z`. The recovery worker sends none and does not seek or expose the chat reference.

## Repository parity

At launch, the outer controller records exact HEAD, `git diff --raw -z`, cached raw diff, and porcelain-v2 status hashes for EA, Chummer design, PropertyQuarry, `/docker/chummercomplete/chummer.run-services`, and `/docker/chummercomplete/chummer-hub-registry`.

PropertyQuarry, run-services, and hub-registry must have exact before/after parity. Chummer may differ only through the two owned files. EA is concurrent external drift: never claim it unchanged; use the worker action log plus targeted path checks to prove zero worker EA writes.

## Final receipt

The wrapper output path is:

`/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_4_WORKER.final.md`

The final worker response must be captured there and include:

- status exactly `proposed_for_independent_re_review`;
- actual fresh worker session ID and `debug_hard` lane;
- this Revision 4 handoff path and exact hash;
- Revision 3 handoff and Revision 2 `REVISE` receipt hashes;
- exhausted Revision 3 worker ID, transcript hash, no-final-receipt status, and all eight recorded process failures;
- exactly two changed files with starting/final hashes and modes;
- explicit closure status for each of the four Revision 2 findings;
- one-clean-run harness implementation description and command/transcript binding;
- named fixtures, exact group counts, intended rejection layer, and results for the complete matrix;
- packet manifest `17/17`, final schema row, and exact proof the other 16 hashes stayed unchanged;
- contract validator, sync classifier, cross-file, stale-authority, literal-alias, and diff-check results;
- before/after repository fingerprints and exact worker action log;
- zero-action counters for every forbidden class;
- assumptions, genericity findings, observability limits, and remaining risks;
- all remaining independent-review, implementation, PropertyQuarry-policy, provider, runtime-journey, privacy, browser/mobile/accessibility, canary, rollback, promotion, and launch gates;
- explicit statement that this is design-contract evidence only and is not implementation, provider, quota, build, publication, promotion, launch, or readiness evidence.

Do not launch an independent reviewer. Do not authorize implementation. Stop after the honest receipt at `proposed_for_independent_re_review`.
