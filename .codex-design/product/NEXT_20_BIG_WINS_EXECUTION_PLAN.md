# Chummer next 20 big wins execution plan

## Framing
The previous wave is materially advanced, but not yet canonically closed end-to-end.

The next wave should execute in this order:

1. kill drift between design truth and public/product truth,
2. make the campaign middle executable,
3. turn Build / Explain / Run / Publish / Improve into the lived product.

## Wave 0 — close truth drift and make the steering loop real

### 1. Publish a real closeout for the previous 15 wins

Owners: `chummer6-design`, `chummer6-hub`, `chummer6-ui`, `chummer6-hub-registry`, `fleet`, `Chummer6`

Exit:
- roadmap, canonical README, release evidence, public progress wording, and the public guide all agree on the same current state
- prior 15 wins are explicitly marked complete, explicitly split into follow-on work, or explicitly demoted from “done” status
- no longer any "execution plan says one thing, guide says another" drift

### 2. Compile the public guide repo from design canon

Owners: `chummer6-design`, `Chummer6`, `fleet`, `chummer6-hub`

Exit:
- the guide repo no longer uses concept-stage / preview language that contradicts the live product surface
- front-door, downloads, support, trust, and “what is real now” pages are generated or refreshed from canonical design manifests
- public fallback routes stop being stale hand-maintained copies

### 3. Promote `PUBLIC_TRUST_CONTENT.yaml` into the canonical and verified set

Owners: `chummer6-design`, `fleet`

Exit:
- `README.md` canonical-set language includes `PUBLIC_TRUST_CONTENT.yaml`
- `scripts/ai/verify.sh` requires it
- trust/help/contact/download pages consume one declared source of truth

### 4. Make the weekly product pulse automatic and decision-relevant

Owners: `chummer6-design`, `fleet`, `chummer6-hub`

Exit:
- weekly scorecard snapshots are published on a schedule
- public progress history has enough depth to replace reliance on planning overrides
- Product Governor decisions cite the pulse directly for freeze / reroute / defer actions

### 5. Introduce a real additive-wave milestone registry

Owners: `chummer6-design`

Exit:
- post-foundation campaign / Build Lab / interop / creator / organizer wave has real milestone IDs, owners, and exit criteria
- “next 20 wins” is steerable canonical truth, not just prose
- scorecard, blockers, and roadmap reference those milestones directly

## Wave 1 — make the campaign middle executable

### 6. Ship `Chummer.Campaign.Contracts` as a real preview package family

Owners: `chummer6-hub`, `chummer6-ui`, `chummer6-mobile`, `chummer6-media-factory`, `chummer6-design`

Exit:
- consumers reference package-owned campaign contracts instead of local shadow shapes
- verification proves package-only consumption in UI, mobile, and media-factory
- package versioning and migration notes are explicit in release evidence

### 7. Make the living dossier a real runtime object

Owners: `chummer6-hub`, `chummer6-ui`, `chummer6-mobile`

Exit:
- a runner can move from build receipt to dossier to play to recap to return without identity drift
- dossier state survives claimed-device handoff and reconnect
- publication-safe dossier projections are first-class instead of ad-hoc exports

### 8. Ship `RuleEnvironment` as first-class truth

Owners: `chummer6-hub`, `chummer6-core`, `chummer6-ui`, `chummer6-mobile`

Exit:
- personal, campaign, and group rule environments exist
- diff, compatibility fingerprint, approval state, and ownership scope are visible
- clients never silently compute against the wrong environment

### 9. Make roaming workspace sync real across claimed devices

Owners: `chummer6-hub`, `chummer6-hub-registry`, `chummer6-ui`, `chummer6-mobile`

Exit:
- recent dossiers, campaigns, rule environments, artifacts, and entitlements restore on a second claimed device
- conflicts are explicit, not silent last-write-wins
- install-local secrets and caches remain local

### 10. Ship the home cockpit and device-role model

Owners: `chummer6-hub`, `chummer6-ui`, `chummer6-mobile`

Exit:
- signed-in home shows next safe action, affected installs, recent dossiers/campaigns, rule drift, and support closure
- device roles such as workstation, play tablet, observer screen, preview scout, and travel cache are visible and actionable
- “what changed for me?” becomes a real product surface

### 11. Deliver the campaign workspace / GM runboard

Owners: `chummer6-hub`, `chummer6-ui`, `chummer6-mobile`

Exit:
- campaign roster, run state, objective state, readiness, recap, and continuity are visible in one workspace
- GM can understand campaign health without stitching together unrelated screens
- campaign return flow behaves as one product, not multiple repos

## Wave 2 — build the first moat: Build + Explain

### 12. Ship the Build Lab backend

Owners: `chummer6-core`

Exit:
- deterministic candidate generation, scoring, comparison hooks, and progression projections are real engine seams
- explain packets exist for every material recommendation
- backend outputs are dossier/campaign handoff ready

### 13. Ship Build Lab UX end to end

Owners: `chummer6-ui`, `chummer6-hub`

Exit:
- users can intake a concept, compare variants, inspect tradeoffs, and hand off a chosen path into dossier/campaign truth
- trap-choice, role-overlap, and progression views are present and grounded
- Build Lab is an explicit product surface, not only a milestone label

### 14. Launch Rules Navigator as a first-class product surface

Owners: `chummer6-core`, `chummer6-ui`, `chummer6-hub`, `chummer6-design`

Exit:
- grounded rule lookup, provenance, and before/after explain are visible to normal users
- users can ask “why did this change?” without moving into internal tooling
- public and signed-in flows share the same grounded truth

### 15. Add interop as a first-class product promise

Owners: `chummer6-design`, `chummer6-core`, `chummer6-hub`

Exit:
- dedicated interop/portability canon is present
- dossier and campaign package formats are explicit
- import/export compatibility becomes part of published product promise

### 16. Complete legacy migration from character-file thinking

Owners: `chummer6-core`, `chummer6-ui`, `chummer6-hub`, `chummer6-design`

Exit:
- users can import/export portable dossier/campaign packages
- legacy import is handled as a transition with explicit receipts
- regression corpus covers character-file compatibility edge cases

## Wave 3 — trust and support as first-class product surfaces

### 17. Turn the public release surface into a real trust surface

Owners: `chummer6-hub`, `chummer6-hub-registry`, `chummer6-ui`, `fleet`

Exit:
- `/downloads`, known issues, release notes, install help, and support status all derive from registry/support truth
- users always see a one recommended installer, current channel posture, and current known issues
- “fixed” language is channel-aware and timing-accurate

### 18. Build the grounded support assistant on real case truth

Owners: `chummer6-hub`, `fleet`, `executive-assistant`, `chummer6-design`

Exit:
- assistant answers only from curated help, release, and support-case sources
- low-confidence paths hand off to case creation or human escalation
- support assistant does not replace case truth

### 19. Create the organizer / community operator layer

Owners: `chummer6-hub`, `executive-assistant`, `chummer6-design`

Exit:
- organizers and operators have first-class campaign/community operational surfaces
- group ownership, permissions, roster state, and campaign visibility are explicit
- community growth stays on the same account/control model as other user flows

### 20. Turn creator publication into a second pillar

Owners: `chummer6-media-factory`, `chummer6-hub`, `chummer6-hub-registry`, `chummer6-design`

Exit:
- creator publication is a named, governed product pillar with manifest, review, and distribution truth
- grounded campaign outputs and creator outputs share provenance and discoverability rules
- publication flow is one coherent, governed pipeline

## Ordering rule

- close truth drift first,
- then make campaign middle executable,
- then build the moat and trust surfaces together.
