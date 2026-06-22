# EA LTD Priority Integrations

This file defines the next LTD integrations that materially improve Executive Assistant without expanding EA Core into a general provider container.

EA Core remains:

- one executive and one operator
- Gmail and Calendar first
- first morning brief
- one review queue
- commitments, decisions, drafts, evidence
- visible review before sensitive send or publication

Provider lanes are allowed only when EA keeps truth, policy, approval, evidence, and release claims.

## Priority Order

1. Hedy meeting evidence
2. MarkupGo + FlipLink premium delivery
3. ApproveThis external approval edge
4. Documentation.AI published docs projection
5. Rafter + Pixefy EA quality gates
6. Deftform, Teable, Answerly, ProductLift, MetaSurvey as later bounded projections

## Hedy Meeting Evidence

Hedy is the highest-impact next lane because meetings create commitments, decisions, follow-ups, and people context that otherwise disappear between email and calendar.

Allowed flow:

```text
Hedy session ends
  -> verify webhook signature
  -> retrieve session
  -> store original transcript as restricted evidence
  -> extract proposed commitments
  -> extract proposed decisions
  -> extract people-memory candidates
  -> create EA review item
  -> operator confirms or rejects
  -> approved objects enter EA
```

Mapping:

```text
transcript / summary -> evidence
action item -> commitment candidate
question requiring choice -> decision proposal
named person/context -> people-memory candidate
follow-up wording -> draft candidate
```

Required controls:

- recording consent is explicit before ingest
- region and meeting identity are recorded
- original transcript is restricted evidence
- correction is possible before promotion
- retention period is recorded for each session
- people memory promotion requires review
- follow-up drafts do not send without review

Hedy must never directly create final commitments, overwrite people memory, or send follow-ups.

## MarkupGo + FlipLink Premium Delivery

EA should feel like delivered work, not a dashboard chore. MarkupGo and FlipLink are the premium output path for approved office work.

Allowed flow:

```text
EA-approved memo or board packet
  -> redaction and access policy
  -> MarkupGo render
  -> artifact hash
  -> optional FlipLink presentation
  -> Emailit delivery
  -> delivery receipt returns to EA Evidence
```

Best deliverables:

- Morning Brief PDF
- Board Preparation Book
- Weekly Commitments Report
- Decision Dossier
- Meeting Follow-up Pack
- Audit and Approval Record
- Executive Travel Brief
- Stakeholder Briefing Book

For private board material, require:

- redaction
- access policy
- link expiration
- revocation
- download policy
- viewer analytics policy
- no public indexing

MarkupGo renders; it does not change content. FlipLink presents; it does not own document truth. EA owns authorization, expiry, redaction, and audit.

## ApproveThis External Approval Edge

ApproveThis is external approval transport, not EA's decision system.

Allowed flow:

```text
EA Decision
  -> operator selects "Request external approval"
  -> EA creates bounded ApproveThis request
  -> external approver responds
  -> EA verifies result
  -> approval event becomes evidence
  -> EA decision state changes
  -> downstream action still passes EA policy
```

Controls:

- every request has an EA decision id
- every callback has a provider event id
- submission idempotency is enforced
- replayed callbacks are rejected
- external result changes only the matching EA decision
- outbound/send/publish actions still require final EA policy checks

ApproveThis must not replace the internal queue, approve broad workspace scope, or trigger direct downstream action.

## Documentation.AI Published Docs Projection

Documentation.AI is a publishing projection for approved docs, not documentation truth.

Allowed flow:

```text
approved markdown
  -> docs build
  -> source hashes
  -> current head binding
  -> freshness check
  -> Documentation.AI publication
  -> link check
  -> llms.txt verification
  -> publication receipt
```

Separate spaces:

- EA Customer Help
- EA Operator Runbook
- EA API and Integration Reference
- EA Security and Trust Center

Do not upload workspace data, customer support tickets, private incident logs, private decision records, or secrets. Provider agent writeback is disabled; no silent product-truth mutation is allowed.

## Rafter + Pixefy EA Quality Gates

Rafter and Pixefy are auxiliary proof gates for EA. They do not own release truth.

Rafter targets:

- approval bypass
- outbound-send authorization
- cross-principal data isolation
- expired-link handling
- provider callback validation
- secret leakage
- false-green release receipts

Pixefy targets:

- /
- /register
- /get-started
- /app/today
- /app/queue
- /app/commitments
- /app/people
- /app/settings
- morning memo email
- approval pages
- mobile layouts
- tablet layouts
- high zoom
- long names
- long subject lines
- error banners
- expired approval links

EA release receipts, tests, and operator approval own release truth. Provider evidence can block a release, but cannot make one green by itself.
