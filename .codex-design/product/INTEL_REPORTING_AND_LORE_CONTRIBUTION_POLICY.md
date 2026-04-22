# Intel reporting and lore contribution policy

## Purpose

This file defines how BLACK LEDGER accepts player, GM, organizer, and curator-submitted lore without letting raw submissions become automatic canon.

The goal is participation with trust.

The practical contribution and reward loop is expanded in `WORLD_INTEL_CONTRIBUTION_AND_REVIEW_POLICY.md`.
The machine-readable state registry lives in `INTEL_REPORT_REVIEW_STATES.yaml`.

## Canonical rule

User-submitted lore is engagement fuel.
It is not automatic world truth.

Every contributed item must carry:

- source identity or pseudonymous contributor path
- scope
- visibility
- spoiler class
- consent posture
- desired-use hints
- review state

## Allowed contribution classes

- rumor
- field report
- district lore
- faction intel
- after-action consequence
- creator seed
- world-operator note

## Minimum report shape

```yaml
intel_report:
  id: intel_2026_05_001
  submitted_by:
    user_ref: user_123
    role: gm
  scope:
    visibility: campaign_private
    world_ref: seattle_shared_01
    region_ref: redmond
    campaign_ref: camp_steel_ghosts
  source_class: user_report
  spoiler_class: gm_only
  confidence: unverified
  title: Mitsuhama clinic rumors in Redmond
  summary: Table lore says a clinic is buying awakened tissue samples.
  desired_use:
    - job_generation
    - district_pressure
    - news_rumor
  provenance:
    consent_ref: consent_abc
    created_at: 2026-05-01T13:00:00Z
  review_state: pending_curator
```

## Review states

- `pending_curator`
- `needs_clarification`
- `reviewed`
- `adopted`
- `merged`
- `rejected`
- `false_flag`
- `canonized`

## Confidence ladder

- `unverified`
- `reviewed`
- `corroborated`
- `adopted`
- `canonized`
- `false_flag`

## Safety rules

### No automatic canonization

User submissions become world truth only after an authorized review or adoption path.

### Spoiler-safe visibility

Every report must carry one of:

- `public`
- `player_safe`
- `campaign_private`
- `gm_only`
- `faction_secret`
- `organizer_only`

### Attribution and consent

Every contributed lore item needs:

- attribution preference
- public-use permission
- reviewable consent receipt
- removal or retirement path where feasible

### No passive surveillance

Session analysis, Table Pulse suggestions, or recap extraction may inform proposed intel only after explicit consent and GM or organizer approval.

### No copyrighted sourcebook ingestion

The system must not encourage users to paste copyrighted rulebook or adventure text as intel.

## Reward posture

Safe contribution loops may include:

- contributor credit on player-safe outputs
- accepted-intel badges
- private notifications when a submission influenced a world tick
- creator or curator role invitations

These rewards must never imply automatic canon authority.
