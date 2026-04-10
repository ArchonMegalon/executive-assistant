# Executive Assistant Flagship Closeout Plan

## Purpose

Turn the existing milestone guide into an execution-order closeout plan for Fleet.

This file is intentionally narrower than `EXECUTIVE_ASSISTANT_MILESTONE_DEV_GUIDE.md`.
It answers one question: what still has to become true before Executive Assistant is honestly flagship-grade for a paying executive office.

## Current verdict

Executive Assistant is credible, but not honestly flagship-grade yet.

The runtime, release discipline, and product shell are already serious.
The remaining gap is that the product promise still outruns the lived workspace in the most expensive trust moments:

- object-driven daily workflow
- operator approvals and evidence
- activation without configuration drag
- commercial and release readiness

## Flagship blockers

### EA-FG-001 — workspace pages are still too shell-driven

`/app/today`, `/app/briefing`, `/app/inbox`, and `/app/follow-ups` still need to behave like durable product-object views instead of narrated previews and onboarding-heavy summaries.

This blocker closes only when Milestones 1 through 3 in `EXECUTIVE_ASSISTANT_MILESTONE_DEV_GUIDE.md` are materially true in the shipped app.

### EA-FG-002 — trust and operator posture still lag the product claim

Approvals, evidence, human-task routing, and admin/operator surfaces must read like a control plane for real customer work, not an endpoint catalog.

This blocker closes only when Milestone 4 is materially true in the shipped app.

### EA-FG-003 — activation is still too configuration-shaped

The first useful loop must happen before messaging-channel or advanced setup sprawl.

This blocker closes only when Milestone 5 is materially true and a first-value path is proven end to end.

### EA-FG-004 — commercial and QA proof is below flagship bar

The product cannot call itself flagship-grade until the release path proves paying-customer readiness, supportability, and stable E2E gates.

This blocker closes only when Milestones 6 and 7 are materially true and the release checklists stay green without caveats.

## Fleet execution order

1. Product object core
   - Make Milestone 1 real first.
   - Introduce product-level objects and a thin product API.
   - Do not spend time on broad landing or design polish until the workspace is object-driven.

2. Daily workflow utility
   - Complete Milestones 2 and 3 next.
   - Make Today, Briefing, Inbox, Follow-ups, commitments, and people graph useful on reload with durable product objects.

3. Trust plane and operator surface
   - Complete Milestone 4 next.
   - Approvals, evidence, and operator/admin views must read like a customer-safe control plane.

4. Activation compression
   - Complete Milestone 5 after the core workflow is real.
   - New workspaces must reach memo, queue, draft, follow-up, and trust receipt without channel-first friction.

5. Paying-customer and QA finish
   - Complete Milestones 6 and 7 last.
   - Commercial posture, reliability, release checks, and E2E proof must line up as one honest product story.

## Flagship release rule

Executive Assistant is not flagship-grade just because:

- `MILESTONE.json` is green
- release asset verification is green
- the landing surface looks polished

It is flagship-grade only when:

- `EA_FLAGSHIP_TRUTH_PLANE.md` and `EA_FLAGSHIP_RELEASE_GATE.json` are green
- the core workspace runs on durable product objects
- one real executive-office loop is faster and safer with the product than without it
- trust, approval, evidence, and handoff are legible in product terms
- activation, release, and support proof tell the same story

## Fleet notes

- Treat `EXECUTIVE_ASSISTANT_MILESTONE_DEV_GUIDE.md` as the broad canon.
- Treat `EA_FLAGSHIP_TRUTH_PLANE.md` as the release oracle for EA-specific flagship claims.
- Treat this file as the closeout order.
- Any “done” claim for Executive Assistant must cite both this file and `PRODUCT_RELEASE_CHECKLIST.md`, plus the EA flagship truth plane.
