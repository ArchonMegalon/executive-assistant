# Teable Admin Projection and Intent Layer

## Purpose

Teable is promoted as Chummer's admin projection and intent-entry layer.

It is not the backbone of Chummer truth. It is the operator workbench where curated slices of Chummer-owned state become easier to inspect, triage, annotate, assign, approve, and return as typed intent.

Core rule:

> Hub owns canonical truth. Teable shows curated projections. Teable edits return as AdminIntents. Hub validates before any canonical write.

## Product role

Teable may provide:

- relational admin tables
- operator dashboards
- curation queues
- review boards
- internal mini-apps
- assignment views
- status filters
- bulk triage views
- admin notes that do not become truth until accepted

Teable must not provide:

- world truth
- campaign truth
- support truth
- rules truth
- release truth
- roster truth
- entitlement truth
- direct runtime database access

## Canonical sync model

```text
Hub canonical object
  -> projection export
  -> Teable table/app
  -> operator edit, approval, triage, note, or assignment
  -> AdminIntent webhook/API back to Hub
  -> Hub validates authority, source version, visibility, and invariants
  -> canonical state changes only inside Hub or the owning service
  -> Teable projection refreshes from canonical state
```

Teable is allowed to help humans move faster. It is not allowed to silently become the place where the product state lives.

## Required projection fields

Every Teable projection row must carry:

```yaml
teable_projection_row:
  projection_id: teable_projection_row_id
  projection_kind: black_ledger_world_tick_review
  source_system: chummer6-hub
  source_contract: Chummer.World.Contracts.WorldTick
  source_id: world_tick_id
  source_version: 7
  source_hash: sha256_of_canonical_projection_payload
  projection_generated_at: 2026-04-26T00:00:00Z
  visibility_class: operator_only
  editable_fields:
    - proposed_status
    - curator_note
    - reviewer_assignment
  forbidden_fields:
    - canonical_status
    - private_runner_state
    - support_case_state
  last_intent_id: admin_intent_id_or_null
  kill_switch_key: teable_black_ledger_admin_workbench
```

## AdminIntent contract

Any Teable-originated write must become an `AdminIntent`.

```yaml
admin_intent:
  intent_id: ai_20260426_001
  idempotency_key: teable_table_row_action_hash
  source_projection_id: teable_projection_row_id
  actor:
    principal_id: hub_operator_id
    role: world_operator
    authority_scope:
      - black_ledger.seattle.tick_review
  requested_action: approve_world_tick_publication
  target:
    source_contract: Chummer.World.Contracts.WorldTick
    source_id: world_tick_id
    expected_source_version: 7
  payload:
    proposed_status: approved_for_public_tick
    curator_note_ref: teable_note_ref
  submitted_at: 2026-04-26T00:00:00Z
  validation:
    requires_hub_authority_check: true
    requires_source_version_match: true
    requires_visibility_policy_check: true
    requires_forbidden_field_scan: true
```

Hub may accept, reject, supersede, or require clarification. Teable must show the returned receipt rather than assuming the edit succeeded.

## Allowed workbenches

Initial Teable workbenches:

- BLACK LEDGER world tick control room
- Intel review queue
- Faction-seat resource submission board
- JobSeed and JobPacket triage
- OpenRun application review
- ResolutionReport review
- NewsReel approval queue
- SeasonalHonors review board
- KARMA FORGE candidate review
- Creator publication queue
- Public signal and support/content curation
- Companion line-pack review queue

## Authority and permissions

Teable permissions are convenience gates, not the final authority model.

Hub must validate:

- user identity
- role and capability scope
- source object version
- object visibility
- faction-secret visibility
- public-safe publication rules
- support and account-data isolation
- duplicate submission and idempotency
- kill-switch state

## Drift prevention

Projection drift is expected. It must be visible.

Required drift handling:

- stale projection banner when `source_version` is not current
- reject writes against old `expected_source_version`
- refresh projection after accepted intent
- keep `AdminIntentReceipt` as the row's return truth
- allow operators to compare projected and canonical state
- never backfill canonical state directly from a Teable export

## Privacy and IP boundary

Teable projections must minimize payloads.

Do not project:

- raw sourcebook text
- private table notes unless explicitly operator-scoped
- player private messages
- raw crash/support payloads
- account secrets
- raw transcripts
- faction secrets into public workbenches

Project structured summaries, IDs, visibility labels, and receipt references instead.

## Rollout gates

Teable cannot become active for a workflow until:

- the owning Hub projection endpoint exists
- the AdminIntent receiver exists
- the idempotency model exists
- projection row fields are documented
- authority checks are tested
- kill switch exists
- export and replay posture exists
- stale-projection UX exists
- privacy scan is defined

## Canonical decision

Teable is a first-class admin workbench for Chummer.
It is not a canonical database.
