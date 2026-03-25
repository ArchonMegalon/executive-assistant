# Participation and guided contribution workflow

## Purpose

This document canonizes the bounded Chummer participation lane for supporters who explicitly sponsor temporary premium work.

It defines:

* user-facing language
* ownership and boundaries
* workflow states
* contract families
* receipt and recognition rules
* rollout posture
* package/bootstrap truth that keeps the workflow buildable

It does not turn Fleet, Hub, or `Chummer6` into independent product authorities.

## User-facing language

Use these terms consistently:

* `participate` is the primary public verb
* `guided contribution` is the public/supporter-facing mode name
* `sponsor session` is the Hub-owned participation record
* `participant lane` is the Fleet/operator execution term
* `contribution receipt` is the signed Fleet event that Hub ingests
* `recognition projection` is the derived leaderboard/badge/feed view

Public copy should prefer `participate` and `guided contribution`.
Operator terms such as `participant burst lane`, `jury`, `core backend`, or `device-auth helper` may appear in operator and verifier surfaces, but they are not first-contact user language.

## Public extract

### `public_pitch`

Chummer supports two clean help lanes:

* the free baseline for bugs, guide feedback, and future-feature suggestions
* the bounded guided contribution lane for supporters who explicitly want to lend temporary premium help

The public promise is simple:

* boosters are opt-in
* boosters are temporary
* boosters are additive on top of the cheap baseline
* final landing still goes through review

### `public_faq`

Public guide/landing copy must be able to answer these questions plainly:

* What is guided contribution?
* Do I need guided contribution to help?
* Why are some things preview-only?
* If a lane starts in guided preview, is the long-run intent broader access later?
* Can I stay private?
* What do badges and leaderboards actually mean?

### `privacy_notes`

Public recognition is opt-in at the user level.
Groups may be publicly visible even when a user keeps personal recognition private.

### `review_safety_notes`

Guided contribution is not a merge bypass.
Participant lanes may help with bounded work, but final landing still routes through review and `jury`.

### `free_later_note`

`booster_first` is a rollout/access posture for expensive early lanes, not a permanent paywall signal.
If a lane starts in guided preview because approvals, compatibility, editorial work, or support burden are high, the long-run intent should still point toward broader access when the cost curve becomes boring enough.

### `public_cta_copy`

Public CTAs should point readers toward:

* the Chummer6 issue tracker for free baseline feedback
* the Hub participation page for the guided contribution lane

## Canonical split

### `chummer6-hub`

Owns:

* sponsor intent and consent truth
* user, group, membership, and visibility truth
* boost codes and sponsor-session read models
* fact ledger, reward journal, and entitlement journal
* receipt ingest, recognition projection, and public/private contribution views
* the user-facing participate/guided-contribution UX

Must not own:

* raw participant Codex/OpenAI auth caches
* Fleet worker lifecycle
* repo landing authority
* provider-runtime accounting truth

### `fleet`

Owns:

* participant-lane provisioning
* device-code auth execution on the worker host
* lane-local auth/cache storage
* participant worker lifecycle
* premium-eligible dispatch policy
* signed contribution receipt emission

Must not own:

* canonical user/group/ledger truth
* participant-consent UX
* product recognition policy
* canonical participation copy or rollout posture

### `executive-assistant`

Owns:

* provider-aware runtime substrate
* lane/provider telemetry
* derived ownership telemetry used by Fleet and Hub
* downstream helper logic that explains or renders design canon

Must not own:

* sponsor-session truth
* public participation policy
* reward or entitlement truth

### `Chummer6`

Owns:

* downstream human explanation of participation canon
* public help/support CTA wording

Must not own:

* canonical workflow rules
* milestone truth
* reward/recognition rules

## Actor model

Canonical actors:

* `supporter` — the authenticated person choosing to help
* `group` — the reusable social/authority container that may sponsor together
* `hub` — the community/accounting plane
* `fleet` — the worker execution plane
* `jury` — the final landing authority
* `ea` — provider/telemetry substrate underneath managed or participant execution

## Workflow state machine

Canonical flow:

1. `discover` — the supporter reads the bounded participation explainer in `Chummer6` or Hub.
2. `authenticate` — the supporter enters Hub using the normal hosted identity flow.
3. `choose_help_mode` — the supporter selects a bounded guided-contribution mode.
4. `sponsor_intent_created` — Hub records the requested project, group, visibility, and help mode.
5. `consent_recorded` — Hub stores the consent record and terms acceptance.
6. `device_auth_pending` — Hub asks Fleet to prepare a participant lane and start worker-host device auth.
7. `device_auth_active` — Hub shows the verification URL and device code returned by Fleet.
8. `lane_pending` — auth is complete and the worker lane is preparing to claim premium-eligible work.
9. `lane_active` — Fleet is executing bounded work on the participant lane.
10. `lane_waiting_review` — a bounded slice is waiting on review or `jury` landing.
11. `lane_stopped` — the supporter or operator has ended the active lane cleanly.
12. `lane_revoked` — the auth cache or lane has been explicitly revoked and cannot resume.
13. `receipt_projected` — Hub has ingested signed contribution receipts from Fleet.
14. `recognition_projected` — Hub has derived badges, scores, feeds, or entitlement changes from those receipts.

Rules:

* stop or revoke must remain legal from `sponsor_intent_created` onward
* if no Fleet lane exists yet, Hub must still be able to close the sponsor session cleanly
* device auth is worker-host initiated by Fleet, not browser- or Hub-host initiated
* `jury` remains the final landing authority even when a participant lane is involved

## Policy rules

* cheap-first remains the default execution posture
* premium participation is additive, not the new default
* participant lanes may claim only premium-eligible work
* receipt-backed value, not raw time or auth completion, drives rewards and recognition
* raw Codex/OpenAI auth material stays lane-local on Fleet
* public recognition is opt-in at the user level and may be group-public while user-private
* protected-preview access is acceptable while the participate surface is still bounded or access-gated
* not every horizon or feature should nudge users toward a guided contribution lane

## Contract family

Canonical participation workflow contracts live under `Chummer.Run.Contracts` unless a later split is explicitly approved in `chummer6-design`.

The family covers:

* sponsor request
* consent record
* device-auth session
* participant-lane state
* contribution receipt
* revoke request
* leaderboard contribution event
* recognition projection

Semantic ownership rules:

* Hub owns sponsor, consent, visibility, ledger, and recognition semantics
* Fleet owns execution-side state transitions, lane identifiers, and receipt signing
* EA may project ownership or provider telemetry, but it must not redefine product workflow semantics

## Recognition rules

Recognition is downstream projection, not system-of-record truth.

Good scoring inputs:

* sponsor session activated
* accepted slice contribution
* landed slice contribution
* first-pass review or `jury` acceptance
* review-clean streaks
* docs/help/bugfix/canon work weight when design explicitly allows it

Bad scoring inputs:

* raw minutes in lane
* raw spend
* raw prompt/turn volume
* auth completion without validated work

Recognition should stay:

* opt-in
* review-safe
* derived from signed receipts
* reversible by moderators/operators

## Rollout posture

Horizon and product surfaces may use these rollout/access fields:

* `access_posture`
  * `public_default`
  * `protected_preview`
  * `booster_first`
  * `invite_only`
* `resource_burden`
  * `low`
  * `medium`
  * `high`
* `booster_nudge`
  * short plain-language explanation for why a lane may begin in guided preview
* `recognition_eligible`
  * whether receipt-backed recognition may be projected publicly for this surface

Rules:

* `booster_first` is valid for high-burden editorial, approval, or compatibility-heavy lanes
* `booster_first` must not be used to hide trust-critical basics behind a support wall
* rollout/access posture is canonical design truth, not ad hoc guide copy

## Package and bootstrap truth

The participation lane is not real if local consumers still fail at restore or bootstrap.

Canonical rule:

* `Chummer.Engine.Contracts` and `Chummer.Ui.Kit` are package-first boundaries

Every consumer must use one of these paths:

1. canonical local/CI package feed
2. explicit generated compatibility tree for legacy consumers

Forbidden bootstrap posture:

* ambient monorepo-relative project references as the assumed default
* half-restored local trees with no clear package feed or compatibility-tree policy

Required bootstrap behavior:

* missing local feed errors must be explicit
* missing generated compatibility-tree errors must be explicit
* Fleet bootstrap may seed feeds or generate compatibility shims, but design owns the policy
* `chummer6-core` and `chummer6-ui-kit` must publish stable package ids and predictable artifacts

## Success bar

This workflow is considered coherent when:

* the user journey is defined here first
* Hub, Fleet, `Chummer6`, and any EA helper compile from this canon
* Fleet no longer needs hidden EA-side canon to verify guide or participation surfaces
* the guide explains the guided contribution lane in plain language
* restore/bootstrap for package-first consumers is deterministic enough to be boring
