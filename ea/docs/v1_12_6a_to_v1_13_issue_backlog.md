# EA OS v1.12.6-a -> v1.13 Issue Backlog

## Usage
Create one GitHub issue per ticket below. Keep labels consistent:

- `area:telegram`
- `area:mum-brain`
- `area:safety`
- `area:llm-gateway`
- `area:operator-surface`
- `area:runbook`
- `area:briefings`
- `type:contract`
- `type:implementation`
- `type:test`
- `priority:p0|p1|p2`

---

## Epic A — v1.12.6-a Baseline Closure

### A1. CI Gate: v1.12.6-a Required Tests
- Priority: `p0`
- Labels: `type:test`
- Scope:
  - enforce `tests/smoke_v1_12_6.py`
  - enforce container design workflow E2E
  - enforce post-live EA log scan gate
- Definition of done:
  - CI fails if any baseline gate fails
  - gate output links to failing step

### A2. Contract Registry in Repo
- Priority: `p0`
- Labels: `type:contract`
- Scope:
  - add contract index page linking all v1.12.x normative contracts
  - mark each contract owner (team alias)
- Definition of done:
  - single index file exists and is referenced from README

### A3. Release Checklist: v1.12.6-a
- Priority: `p0`
- Labels: `type:implementation`
- Scope:
  - codify release preconditions from patch memo
  - include rollback notes
- Definition of done:
  - release checklist used by `scripts/release_v126_avomap.sh`

---

## Epic B — Telegram Interaction Contract Implementation

### B1. Briefing Size Budget Enforcer
- Priority: `p0`
- Labels: `area:telegram`, `type:implementation`
- Scope:
  - implement 3500 target / 3900 hard cap trim policy
  - preserve critical blockers/actions
- Definition of done:
  - over-budget payloads are trimmed deterministically
  - no outbox send fails due to message length

### B2. Callback Token Lifecycle Hardening
- Priority: `p0`
- Labels: `area:telegram`, `type:implementation`
- Scope:
  - single-use + TTL + user/chat binding validation
  - explicit expired/invalid user copy
- Definition of done:
  - replayed token cannot trigger side effects

### B3. Edit-vs-Follow-Up Arbiter
- Priority: `p1`
- Labels: `area:telegram`, `type:implementation`
- Scope:
  - central helper deciding edit vs follow-up vs suppress
  - bounded enhancement window
- Definition of done:
  - same enhancement correlation id delivers at most once

### B4. Telegram Contract Smoke Suite
- Priority: `p0`
- Labels: `area:telegram`, `type:test`
- Scope:
  - budget trim test
  - callback expiry test
  - duplicate follow-up suppression test
  - HTML-safety send test
- Definition of done:
  - all tests run in host smoke and container smoke

---

## Epic C — Mum Brain Repair Contract Implementation

### C1. Failure Class Enum + Mapping
- Priority: `p0`
- Labels: `area:mum-brain`, `type:implementation`
- Scope:
  - normalize failure classes to contract list
  - map current runtime exceptions/events into classes
- Definition of done:
  - unknown classes are rejected or mapped to explicit fallback class

### C2. Bounded Retry Policy Engine
- Priority: `p0`
- Labels: `area:mum-brain`, `type:implementation`
- Scope:
  - enforce retryable vs non-retryable matrix
  - enforce attempt/time budgets
- Definition of done:
  - no unbounded retries
  - optional failures never block primary response

### C3. Breaker Policy Compliance
- Priority: `p1`
- Labels: `area:mum-brain`, `type:implementation`
- Scope:
  - open/half-open/close behavior per class
  - TTL handling and suppression path
- Definition of done:
  - breaker opens on threshold and suppresses flapping optional paths

### C4. Repair Audit Completeness Test
- Priority: `p0`
- Labels: `area:mum-brain`, `type:test`
- Scope:
  - assert required audit fields for each repair decision
- Definition of done:
  - missing field fails test

---

## Epic D — Household Safety Contract Implementation

### D1. Confidence Band Policy Gate
- Priority: `p0`
- Labels: `area:safety`, `type:implementation`
- Scope:
  - enforce high/medium/low confidence behavior
  - map action classes to allowed bands
- Definition of done:
  - low confidence cannot execute side effects

### D2. Fail-Closed Blocklist Enforcement
- Priority: `p0`
- Labels: `area:safety`, `type:implementation`
- Scope:
  - hard-block high-risk autonomous action classes
- Definition of done:
  - blocked classes are denied even under transient policy errors

### D3. Blind Triage and Replay Idempotency
- Priority: `p1`
- Labels: `area:safety`, `type:implementation`
- Scope:
  - ensure low-confidence requests route to triage
  - replay path requires idempotency key
- Definition of done:
  - replay never duplicates side effects

### D4. Evidence Reveal Audit Tests
- Priority: `p1`
- Labels: `area:safety`, `type:test`
- Scope:
  - claim TTL and reveal audit behavior
- Definition of done:
  - unauthorized reveal attempt is blocked and logged

---

## Epic E — Cloud LLM Gateway Contract Implementation

### E1. Egress Redaction Guard
- Priority: `p0`
- Labels: `area:llm-gateway`, `type:implementation`
- Scope:
  - pre-egress sanitizer with forbidden-field checks
- Definition of done:
  - forbidden fields are blocked before provider call

### E2. Output Validator Pipeline
- Priority: `p0`
- Labels: `area:llm-gateway`, `type:implementation`
- Scope:
  - implement validator classes:
    - schema invalid
    - policy invalid
    - unsafe content
- Definition of done:
  - rejected output always falls back safely

### E3. Egress Audit Query Completeness
- Priority: `p1`
- Labels: `area:llm-gateway`, `type:test`
- Scope:
  - verify model/provider/task/token/sanitizer/validator fields are logged
- Definition of done:
  - audit lookup returns complete egress record

---

## Epic F — Minimal Operator Surface

### F1. Review Queue API/UX Slice
- Priority: `p1`
- Labels: `area:operator-surface`, `type:implementation`
- Scope:
  - list + claim + decide workflow
- Definition of done:
  - claim token TTL and actor attribution enforced

### F2. Connector Auth Repair Slice
- Priority: `p1`
- Labels: `area:operator-surface`, `type:implementation`
- Scope:
  - connector auth status + re-auth trigger + recovery signal
- Definition of done:
  - auth recovery closes related auth breaker when policy allows

### F3. DLQ + Replay Slice
- Priority: `p1`
- Labels: `area:operator-surface`, `type:implementation`
- Scope:
  - list DLQ items, inspect redacted hints, replay one item
- Definition of done:
  - replay path policy-checked and fully audited

### F4. Breaker + Egress Lookup Slice
- Priority: `p2`
- Labels: `area:operator-surface`, `type:implementation`
- Scope:
  - breaker status panel
  - egress audit search panel
- Definition of done:
  - routine failure triage possible without shell access

---

## Epic G — Runbook Behavior Execution

### G1. Scenario Runbook Pages
- Priority: `p1`
- Labels: `area:runbook`, `type:implementation`
- Scope:
  - one page per scenario in runbook behavior contract
  - include trigger/expected/user/operator sections
- Definition of done:
  - pages link from main runbook

### G2. Game-Day Simulations
- Priority: `p1`
- Labels: `area:runbook`, `type:test`
- Scope:
  - simulation scripts for:
    - LLM outage
    - renderer outage
    - token expiry
    - credit exhaustion
    - prompt-injection rejection
- Definition of done:
  - each simulation has PASS/FAIL criteria

---

## Epic H — v1.13 Actionable Briefings

### H1. Safe Action Card Schema
- Priority: `p0`
- Labels: `area:briefings`, `type:implementation`
- Scope:
  - standard action card with why/proposed action/approve-edit-dismiss
- Definition of done:
  - schema validated before Telegram render

### H2. Action Execution Envelope
- Priority: `p0`
- Labels: `area:briefings`, `type:implementation`
- Scope:
  - correlation id + idempotency key + policy class + confidence band
- Definition of done:
  - every action execution request carries full envelope

### H3. Safe Actions v1
- Priority: `p1`
- Labels: `area:briefings`, `type:implementation`
- Scope:
  - draft email
  - task draft
  - re-auth trigger
  - approval staging
  - calendar suggestion draft
- Definition of done:
  - all paths are policy-checked and auditable

### H4. Blocked High-Risk Action Regression
- Priority: `p0`
- Labels: `area:briefings`, `type:test`
- Scope:
  - assert high-risk autonomous actions remain blocked
- Definition of done:
  - blocked classes cannot be executed through briefing actions

---

## Suggested Milestone Grouping
- Milestone `v1.12.6-a-close`:
  - A1-A3, B1-B4, C1-C4, D1-D4, E1-E3
- Milestone `v1.12-operator-min`:
  - F1-F4, G1-G2
- Milestone `v1.13-actionable-briefings`:
  - H1-H4

