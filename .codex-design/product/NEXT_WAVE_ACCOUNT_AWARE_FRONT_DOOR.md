# Chummer next-wave milestone list

## Recommended initiative

**Account-Aware Front Door**

This wave turns `chummer.run` into a real account-aware install, update, and support surface backed by Hub + Registry + UI while tightening the design/control loop in `chummer6-design` and Fleet.

Some `M0` ingredients already exist in canon today.
This wave closes the remaining coherence, coverage, and runtime-loop gaps so those surfaces stop feeling provisional.

## Canon closure for M129

M129 closes the public-auth, identity and channel-linking, participation, account-aware front-door, and community-ledger canon into one reusable story.

The closure binds these design-owned sources together:

* `PUBLIC_AUTH_FLOW.md` for the guest-to-registered route split
* `PUBLIC_USER_MODEL.md` for guest, registered, claimed-install, and community-ledger posture
* `IDENTITY_AND_CHANNEL_LINKING_MODEL.md` for linked identities, linked channels, and companion-channel boundaries
* `ACCOUNT_AWARE_INSTALL_AND_SUPPORT_LINKING.md` for install claim, channel posture, and recovery truth
* `COMMUNITY_SPONSORSHIP_BACKLOG.md` for the Hub/Fleet/EA community-ledger split

Rules:

* one public account-aware front door exists
* `/participate` is the guest-readable entry; `/home` and `/account` are the signed-in shells
* claim, participation, reward, entitlement, channel, and recovery posture must map back to the same Hub-owned community ledger
* Fleet receipt semantics stay downstream evidence, not account truth

## Milestones

### M0 — Canon and control-loop closure

**Owners:** `chummer6-design`, `fleet`

* Keep downloads, auto-update, support/feedback status, and operator/OODA canon complete and verifier-covered.
* Reconcile milestone language so "foundation release complete at canonical design level" stays distinct from "public product maturity is still advancing."
* Extend `CONTRACT_SETS.yaml` with explicit versioning and deprecation metadata.
* Keep `executive-assistant` inside the governance perimeter as a first-class control-plane substrate while preserving advisory-only status on canon ownership.
* Keep public front-door and control-loop docs under validator coverage.

**Exit:** No dangling policy references, no ambiguous operator ownership, and validator coverage includes the public front door plus the control loop.

### M1 — Durable Hub community and account spine

**Owners:** `chummer6-hub`

* Make product users, groups, memberships, join or boost codes, ledgers, sponsor sessions, and linked identities durable.
* Keep user truth separate from principal and session truth.
* Keep facts, rewards, and entitlements visibly separate.
* Converge public participation onto this single durable model.

**Exit:** Restart-safe state, no parallel participation-intent model, and one reusable account/group/ledger substrate.

### M2 — Registry release/install/update model

**Owners:** `chummer6-hub-registry`

* Model installer/download records, release-channel heads, update-feed metadata, install history, compatibility projections, and release-note/read-model projections.
* Make Registry the only owner of promoted install and update truth.

**Exit:** Hub can render `/downloads` from Registry-only read models, and UI can resolve update truth from Registry-owned metadata.

### M3 — Public downloads and signed-in install surfaces

**Owners:** `chummer6-hub`

* Ship `/downloads`, `/home`, and `/account` around registry-backed install and update state.
* Support guest downloads for public preview and stable lanes.
* Add signed-in recommendation surfaces for what to install, which channel the user is on, what changed, and what needs attention.

**Exit:** The public front door is no longer just a promise shelf; it is a real install surface.

### M4 — Desktop self-update and install linking

**Owners:** `chummer6-ui`, `chummer6-hub`, `chummer6-hub-registry`

* Turn the existing desktop update-manifest seam into a full updater client.
* Add staged apply/restart, rollback guardrails, and first-run install registration/linking to Hub.
* Keep one signed installer per `head × platform × arch × channel`; do not personalize binaries.

**Exit:** A preview desktop head can update itself end to end and appear as a known install in the signed-in Hub surface.

### M5 — Crash, bug, and feedback closure loop

**Owners:** `chummer6-ui`, `chummer6-hub`, `fleet`

* Add crash envelopes, bug reports, feedback submissions, support cases, status timelines, and notification hooks.
* Route raw intake through Hub, clustering/triage through Fleet, and design-impact items back into `chummer6-design`.
* Only send "fixed" notifications when the fix reaches the reporter's channel.

**Exit:** A user report can be received, triaged, fixed, and closed with visible status.

### M6 — Operator and design OODA loop

**Owners:** `chummer6-design`, `fleet`, `chummer6-hub`, `executive-assistant`

* Replace the root `feedback/` staging area with a governed intake -> cluster -> decision-packet -> canon-update loop.
* Publish operator rules for when signals become code tasks, docs tasks, or design changes.
* Keep user-facing support truth in Hub, execution truth in Fleet, and cross-repo canon in design.

**Exit:** No semi-canonical scratch inbox; product reality is compiled back into canon through a real loop.

### M7 — Validation and mirror hardening

**Owners:** `chummer6-design`, `fleet`

* Replace hardcoded local mirror paths and old repo aliases.
* Introduce schema/invariant validation for contracts, milestones, progress artifacts, and the new public/control docs.
* Stop mirroring the exact same product bundle everywhere when narrower repo-specific bundles would do.

**Exit:** Portable mirror publish, stronger validator coverage, and less downstream cognitive spam.

## What not to do first

* Do **not** prioritize more booster gamification before the durable Hub substrate is honest.
* Do **not** spend the next wave on more horizon storytelling without closing the install/update/support loop.
* Do **not** add more Fleet-side community logic ahead of Hub-owned account/group/ledger truth.
