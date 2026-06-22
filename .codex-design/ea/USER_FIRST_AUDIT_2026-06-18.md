# EA User-First Audit - 2026-06-18

This audit treats the user outcome as the product boundary. EA should feel like one dependable executive office: one useful memo, one review queue, one commitment system, visible evidence, and no invisible automation for sensitive work.

## Current User-First Priorities

1. Meetings must become reviewable work without losing evidence.
2. Delivered work must feel finished: memos, board packs, approval records, and handoff packets need hashes, redaction, and access policy.
3. External approval must not fork EA truth.
4. Customer/operator docs must publish from source-controlled truth.
5. Release quality must block on security and visual defects at the current source head.

## Fixed In This Pass

### Hedy meeting evidence

Added executable Hedy meeting-evidence contracts:

- explicit recording consent before transcript storage
- HMAC webhook verification with timestamp replay protection
- webhook idempotency
- restricted transcript evidence candidates
- commitment, decision, people-memory, and draft candidates marked review-required
- no direct commitment creation, memory promotion, or follow-up sending

Tests:

- `tests/test_hedy_meeting_evidence.py`

### MarkupGo + FlipLink premium delivery

Added a governed premium-delivery packet for approved EA documents:

- approved source packet required
- raw Gmail, raw Calendar, secrets, people memory, and unredacted board material blocked
- private board packets require redaction and access policy
- rendered artifacts are hashed
- FlipLink is presentation only, not truth
- direct publish and provider content mutation are blocked

Tests:

- `tests/test_premium_delivery.py`

### ApproveThis external approval edge

Added an external-approval contract:

- only bounded EA Decisions can leave EA
- approver contact is hashed in receipts
- signed callbacks are required
- stale/replayed callbacks are rejected
- provider result returns as EA Evidence
- EA decision update remains final-policy-gated
- no downstream send/publish/action is allowed from provider state alone

Tests:

- `tests/test_approvethis_external_approval.py`

### Documentation.AI published docs projection

Added a source-bound docs publication packet:

- approved Markdown/MDX/text docs only
- source git head required
- source hashes and source-tree fingerprint materialized
- `llms.txt` required and hashed
- link check required
- workspace data, support tickets, incident logs, private decisions, and secrets blocked
- provider writeback remains disabled

Tests:

- `tests/test_documentation_ai_publication.py`

### Rafter + Pixefy EA quality gates

Added an EA-specific quality-gate receipt:

- required Rafter security targets are enumerated
- required Pixefy visual targets are enumerated
- missing, failing, or stale provider evidence blocks release
- provider evidence can block a release but cannot make one green
- release truth remains with EA receipts, tests, and operator approval

Tests:

- `tests/test_ea_quality_gates.py`

### Provider contract receipts and operator visibility

Added a materialized contract-receipt layer for the new provider workflow contracts:

- Hedy meeting evidence contract receipt
- MarkupGo + FlipLink premium delivery contract receipt
- ApproveThis external approval contract receipt
- Documentation.AI publication contract receipt
- EA Rafter/Pixefy quality-gates contract receipt
- summary verifier that rejects live-provider and gold overclaims

The Providers admin page now shows a visible `Provider contract receipts` card. It tells the operator which local contracts pass and which live-provider receipts are still required, instead of hiding the evidence in generated JSON.

Tests and receipts:

- `scripts/materialize_ea_provider_contract_receipts.py`
- `scripts/verify_ea_provider_contract_receipts.py`
- `tests/test_ea_provider_contract_receipts.py`
- `tests/test_provider_contract_status.py`
- `tests/test_ltd_runtime_api.py`
- `tests/test_admin_surface_runtime_contracts.py`

### Hedy webhook to EA review queue

Added a public HMAC-verified Hedy webhook intake that turns a consented meeting into exactly one EA human review task:

- default-off route at `/v1/integrations/hedy/webhook`
- requires `EA_HEDY_MEETING_EVIDENCE_ENABLED=1`, `EA_HEDY_WEBHOOKS_ENABLED=1`, and a webhook secret
- rejects bad signatures and oversized/invalid payloads
- derives the principal from the signed payload or an explicit configured default
- blocks unconsented transcripts without creating a review task
- creates one `hedy_meeting_review` human task for consented sessions
- includes restricted evidence candidates, commitment candidates, decision candidates, people-memory candidates, and draft candidates in the review payload
- dedupes signed webhook retries by Hedy idempotency key so the operator queue does not get duplicate meeting reviews
- still does not create final commitments, decisions, memory, or outbound follow-ups

Tests and receipts:

- `ea/app/api/routes/hedy_integration.py`
- `ea/app/services/hedy_meeting_review_intake.py`
- `tests/test_hedy_meeting_review_intake_api.py`
- `_completion/ea_provider_contracts/HEDY_MEETING_EVIDENCE_CONTRACT.generated.json`

## Remaining Product Gaps

These are intentionally not marked complete by contract-only work.

### Live provider receipts

The new contract services still need live/provider-backed receipts before promotion:

- Hedy account/API/webhook capability
- MarkupGo render roundtrip
- FlipLink private-packet access policy
- ApproveThis provider capability and callback proof
- Documentation.AI site allocation, publication, and `llms.txt` proof
- EA-specific Rafter and Pixefy runs at the current source head

### Operator UI integration

Partially fixed: the Providers admin surface now exposes the contract receipt overview and does not overclaim live-provider proof.

The next implementation pass should expose lane-specific work in the operator surfaces:

- meeting evidence review item
- premium packet render/review state
- external approval request/result detail
- docs publication readiness
- release-quality blocker view

### Persistence and receipts

The contracts are deterministic and tested, but production needs durable ledgers:

- provider event idempotency persisted outside process memory
- packet receipts materialized under `.codex-studio/published` or `_completion`
- source HEAD and workflow run IDs attached to release receipts
- retention/deletion jobs for sensitive transcripts and private packet artifacts

### End-to-end tests

Focused unit tests now cover the policy boundaries. Still needed:

- Live Hedy provider webhook -> EA review queue receipt from a real Hedy event
- approved board packet -> MarkupGo render -> FlipLink presentation -> Emailit delivery receipt E2E
- EA decision -> ApproveThis request -> callback -> Evidence -> final EA policy gate E2E
- approved docs -> Documentation.AI projection -> link/llms verification E2E
- EA release candidate -> Rafter/Pixefy evidence -> release gate E2E

## User-First Verdict

The product is stronger after this pass because the top provider lanes now speak EA's native language: evidence, drafts, decisions, commitments, review, hashes, and release gates.

The operator surface is also more honest: contract proof is visible, but it still says live provider proof is pending.

Do not claim these lanes are live until provider receipts and E2E runs exist. The correct status is:

```text
Contract layer: implemented and tested.
Live provider runtime: pending provider receipts and E2E proof.
```
