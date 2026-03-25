# Executive Assistant — Milestone Dev Guide

## Purpose

This guide is a development plan for moving the current Executive Assistant repository from a credible product shell plus strong runtime into a polished, smart, useful product that a paying customer can trust with real work.

The current repo is already good enough to build on. It has a clear product thesis, a calmer public surface, a real runtime, a release checklist, and smoke/contract coverage. The missing step is not another round of copy or styling. The missing step is to make the workspace operate on real product objects and real daily work.

This guide assumes the target wedge is:

- one executive
- one operator or chief of staff
- Gmail + Calendar first
- one morning memo
- one decision queue
- one commitment system
- explicit approvals and auditability

That wedge is narrow on purpose. It is the fastest route to a paying customer.

---

## Current repo audit

### What is already strong

1. **The thesis is much clearer than before.**
   The README and product brief now describe Executive Assistant as an operating system for one executive office rather than a generic assistant shell.

2. **The top-level navigation is in the right shape.**
   Public, app, and admin surfaces are separated. That is the correct information architecture.

3. **The runtime looks serious.**
   The app mounts channels, delivery, evidence, human tasks, memory, onboarding, plans, policy, providers, responses, tools, and task contracts. This is not a toy backend.

4. **The repo already has production discipline.**
   There is a smoke workflow, Postgres smoke scripts, legacy migration regression smoke, a release checklist, and CI gate commands.

5. **Brand drift is now actively guarded.**
   The browser surface contract tests explicitly fail if old drift words leak into rendered pages.

### What is still weak

1. **The app shell is still ahead of the product.**
   The main workspace pages are still assembled mostly from onboarding status, view-model summaries, queue previews, and helper copy. That means the UI is narrating the intended product instead of showing real product objects.

2. **Admin surfaces are still endpoint catalogs.**
   The admin payloads explain which APIs matter, but they do not yet feel like a useful control plane for a paying customer deployment.

3. **Onboarding still behaves like configuration, not activation.**
   The current flow is much better than before, but it still exposes optional messaging and advanced posture too early.

4. **Side surfaces still exist in the repo even though the product shell is cleaner.**
   `public_results` and `public_tours` are now feature-flagged instead of always mounted, which is correct, but they still represent scope drag inside the main codebase.

5. **The browser layer still has large template and route files.**
   `landing.py`, `base_public.html`, `base_console.html`, and `get_started.html` are still substantial. That is manageable, but it will slow product iteration and blur concerns if left as-is.

6. **The product promise and the product model are not fully aligned yet.**
   The product brief says channels should feed core objects instead of defining the product. The actual app pages still depend heavily on onboarding and channel state.

### Plain-language verdict

The repository has moved from “clever runtime with mixed product identity” to “credible product shell with a real backend.”

The next leap is to move from **shell-driven pages** to **object-driven workflow**.

---

## Design principles for every next change

Use these as hard filters.

### 1. The product is a work system, not a dashboard
If a page exists only to summarize configuration, it is probably the wrong page. Every important screen should help the customer make a decision, approve an action, close a commitment, or understand why the assistant believes something.

### 2. Channels are inputs, not the product center
Email, calendar, Telegram, and WhatsApp are useful only because they create commitments, decisions, drafts, evidence, and people context.

### 3. The web app is secondary to the daily loop
The most important user experience is: get the memo, clear the queue, approve or reject, close follow-ups, hand off cleanly. The web app should support that loop, not replace it.

### 4. The first paying customer buys reliability and judgment, not feature count
Do not widen channel support or public utility surfaces until the Gmail + Calendar loop is strong enough that a human would miss it if you turned it off.

### 5. Trust must be legible
Every draft, memory entry, recommendation, and follow-up should be explainable: where it came from, what evidence supports it, what rule gated it, and what human approved it.

---

## What to stop doing now

Before starting the milestones below, make these negative decisions explicit:

1. Do not add new channels unless they directly improve the Google-first loop.
2. Do not grow the public landing surface again until the product workflow is materially better.
3. Do not keep property-tour or public-result functionality in the core product path unless it directly supports the EA offering.
4. Do not treat copy, nav, or hero polish as product progress.
5. Do not ship more placeholder cards that summarize intent instead of work objects.

---

## Milestone 0 — Freeze the product boundary

### Goal
Make the repository reflect one product and one wedge.

### Why this matters
The codebase is already clearer, but the repo still carries optional public utility routes and legacy residue. That creates product ambiguity and slows decision-making.

### Deliverables

- a single published product boundary
- side surfaces moved behind flags or a separate app package
- documentation and tests updated to enforce the boundary

### Implementation steps

#### 0.1 Remove or isolate sidecar routes
Keep `ea/app/api/app.py` gating `public_results_router` and `public_tours_router` behind explicit flags.

Recommended default posture:

- `EA_ENABLE_PUBLIC_RESULTS=false`
- `EA_ENABLE_PUBLIC_TOURS=false`

If they remain strategically useful, move them into a separate namespace such as:

- `ea/app/experiments/public_results.py`
- `ea/app/experiments/public_tours.py`

#### 0.2 Quarantine legacy residue
Move clearly non-core assets such as `chummer6_guide` into one of:

- a separate repo
- `/legacy`
- `/labs`
- an archival branch

Do not leave them in the root of the main product repo if the team wants the product story to stay clean.

#### 0.3 Make the product boundary explicit in docs
Update:

- `README.md`
- `PRODUCT_BRIEF_V2.md`
- `ARCHITECTURE_MAP.md`
- `RELEASE_CHECKLIST.md`

Add one short section called **Core Product Boundary** listing exactly what is in scope for the paying-customer product.

#### 0.4 Add tests that enforce the boundary
Extend `tests/test_browser_surface_contracts.py` or add a new suite that asserts:

- no public nav item links to non-core surfaces
- no link on `/`, `/product`, `/pricing`, `/docs`, or `/get-started` points to experimental routes
- experimental routes are unavailable in product mode

### Acceptance criteria

- the default app no longer mounts public tours or public results
- no legacy or side-brand language is reachable from the browser surface
- docs state the core product boundary in one place
- the browser surface tests fail if the boundary is violated

---

## Milestone 1 — Introduce product-level objects and a thin product API

### Goal
Stop building the workspace from onboarding and helper copy. Build it from durable product objects.

### Why this matters
This is the single most important technical step. Right now the product brief is object-centric, but the app shell is still driven by `brief_preview`, queue summaries, and descriptive copy. That keeps the product one abstraction layer away from being real.

### Product objects to introduce

Create a product domain package, for example:

- `ea/app/product/models.py`
- `ea/app/product/service/`
- `ea/app/product/projections/`

Define these objects first:

1. `BriefItem`
2. `DecisionQueueItem`
3. `Commitment`
4. `DraftCandidate`
5. `PersonProfile`
6. `EvidenceRef`
7. `PolicyGate`
8. `HandoffNote`

### Suggested object shape

#### `BriefItem`
Fields:

- `id`
- `workspace_id`
- `kind` (`priority`, `risk`, `meeting`, `follow_up`, `draft`, `decision`)
- `title`
- `summary`
- `score`
- `why_now`
- `evidence_refs[]`
- `related_people[]`
- `related_commitment_ids[]`
- `recommended_action`
- `status`

#### `DecisionQueueItem`
Fields:

- `id`
- `queue_kind` (`approve_draft`, `confirm_memory`, `assign_owner`, `choose_option`, `close_commitment`, `defer`)
- `title`
- `summary`
- `priority`
- `deadline`
- `owner_role`
- `requires_principal`
- `evidence_refs[]`
- `resolution_state`

#### `Commitment`
Fields:

- `id`
- `source_type` (`email`, `calendar`, `note`, `chat`, `manual`)
- `source_ref`
- `statement`
- `owner`
- `counterparty`
- `due_at`
- `status` (`open`, `waiting`, `scheduled`, `done`, `dropped`)
- `last_activity_at`
- `risk_level`
- `proof_refs[]`

#### `DraftCandidate`
Fields:

- `id`
- `thread_ref`
- `recipient_summary`
- `intent`
- `draft_text`
- `tone`
- `requires_approval`
- `approval_status`
- `provenance_refs[]`
- `send_channel`

#### `PersonProfile`
Fields:

- `id`
- `display_name`
- `role_or_company`
- `importance_score`
- `relationship_temperature`
- `open_loops_count`
- `latest_touchpoint_at`
- `preferred_tone`
- `themes[]`
- `risks[]`

### API layer

Create a BFF-style product API, separate from raw runtime routes.

Suggested routes:

- `GET /app/api/brief`
- `GET /app/api/queue`
- `GET /app/api/commitments`
- `GET /app/api/commitments/{id}`
- `GET /app/api/drafts`
- `POST /app/api/drafts/{id}/approve`
- `POST /app/api/queue/{id}/resolve`
- `GET /app/api/people`
- `GET /app/api/people/{id}`
- `GET /app/api/handoffs`

This layer should compose data from existing memory, evidence, delivery, human, policy, plans, and response services rather than exposing those raw systems directly to the browser.

### Repo changes

- keep `landing_content.py` for marketing copy only
- keep `landing.py` for route/auth/template orchestration only
- retire the app data assembly logic in `landing_view_models.py` once object-backed view models exist
- introduce `workspace_view_models.py` that consumes product objects instead of onboarding state

### Tests

Add:

- `tests/test_product_api_contracts.py`
- `tests/test_product_brief_assembly.py`
- `tests/test_decision_queue_projection.py`
- `tests/test_commitment_projection.py`

### Acceptance criteria

- `/app/*` pages can render from product API payloads without depending on `brief_preview`
- all top-level workspace pages correspond to one or more product objects
- product APIs have stable response contracts and tests

---

## Milestone 2 — Make Today, Briefing, Inbox, and Follow-ups actually useful

### Goal
Replace narrative placeholders with a working daily loop.

### Why this matters
This is where the product starts becoming worth paying for.

### The target loop
A customer should be able to do this with confidence:

1. receive the morning memo
2. open the queue
3. review a proposed draft
4. close or defer a follow-up
5. understand why the assistant suggested those actions

### Screen-by-screen rebuild

#### Today
Turn `Today` into a ranked queue of the day.

Required sections:

- top priorities
- blocked decisions
- today’s at-risk commitments
- pending approvals
- recent stakeholder changes

Each row should have:

- title
- one-sentence why-it-matters
- source/evidence badge
- one next action

#### Briefing
Turn `Briefing` into a real memo reader.

Required sections:

- overnight changes
- calendar pressure
- people to respond to
- commitments at risk
- decisions blocked
- suggested sequence for the day

Add actions:

- convert to queue item
- open draft
- mark not relevant
- correct memory

#### Inbox
Rename the mental model internally from “inbox” to **draft queue / response queue** even if the URL stays the same for now.

Required sections:

- ready-for-review drafts
- needs-more-context drafts
- waiting-on-human drafts
- stale drafts

Each item should show:

- recipient summary
- thread context
- why now
- provenance/evidence
- approval status
- one-click actions: approve, edit, reject, assign

#### Follow-ups
Rebuild this as the **commitment ledger** or keep the current route and change the page title later.

Required sections:

- due today
- waiting on others
- unresolved promises
- stale commitments
- recently closed

Each item should show:

- commitment statement
- owner
- counterparty
- due date
- latest activity
- risk marker
- close/snooze/assign action

### Message and memo delivery
Use the existing delivery layer to send:

- one morning memo
- one end-of-day handoff summary
- approval notifications when necessary

### Tests

Add end-to-end business tests around:

- brief generated from fixture email + calendar data
- draft enters queue and can be approved
- commitment extracted from a thread and can be closed
- queue state survives refresh and re-render

### Acceptance criteria

- the four main pages help a human complete actual work
- each item has evidence and a clear next action
- the product can demonstrate a full daily loop on fixture data without relying on placeholder copy

---

## Milestone 3 — Build the commitment engine and people graph

### Goal
Make the product smart in a way that customers feel every day.

### Why this matters
A useful executive assistant product does not win on generic chat. It wins on not dropping balls and on understanding who matters.

### Part A: Commitment engine

#### Build commitment extraction
From email, calendar, and approved notes, extract commitments such as:

- promises to reply
- promises to send material
- meeting follow-ups
- owner assignments
- externally expected deadlines

#### Add a review path
Never silently write high-confidence commitments into the ledger without a review path. Use one of:

- automatic low-risk insert + visible correction UI
- queue-for-confirmation
- confidence threshold with workspace policy

#### Add commitment lifecycle transitions
Support:

- open
- waiting on external party
- scheduled
- done
- dropped with reason
- deferred with explicit date

#### Add risk scoring
Score commitments using:

- deadline proximity
- inactivity age
- stakeholder importance
- number of unresolved reminders
- relationship temperature

### Part B: People graph

Merge memory + contacts + recent activity into one product view.

#### Build `PersonProfile` projections
For each relevant person, derive:

- latest touchpoints
- open commitments
- relationship heat
- recurring themes
- risk signals
- preferred tone / cadence

#### Create person detail pages
New surfaces:

- `/app/people`
- `/app/people/{id}`

Each person detail view should include:

- recent interactions
- open loops
- current drafts
- recent decisions involving that person
- memory entries with provenance

#### Add memory correction UI
Customers must be able to say:

- this is wrong
- do not remember this
- remember this differently
- this belongs to another person/workspace

### Suggested repo additions

- `ea/app/product/commitments.py`
- `ea/app/product/people.py`
- `ea/app/product/extractors/`
- `ea/app/templates/app/people_detail.html`

### Acceptance criteria

- new commitments can be derived from real source data and reviewed
- stale commitments surface automatically
- each high-value person gets a durable product profile, not just a transient contact list entry

---

## Milestone 4 — Operator workflow, approvals, and trust surfaces

### Goal
Make the product viable for one executive plus one operator.

### Why this matters
That is the cleanest paying-customer wedge in the current product brief and pricing structure.

### Part A: Handoff model

Introduce explicit roles:

- principal
- operator
- reviewer
- admin

#### Add handoff objects
Create `HandoffNote` and `QueueAssignment` objects with:

- queue item refs
- summary written by assistant or operator
- owner
- due time
- escalation status

#### Build operator-focused views
New or reworked sections:

- operator queue
- assigned items
- waiting on principal
- recent decisions
- handoff summary

### Part B: Approvals

The approval model should be visible and helpful, not just safe.

For every draft or sensitive action, show:

- what action will happen
- what evidence supports it
- what rule requires approval
- who can approve it
- what changes after approval

### Part C: Real admin surfaces

Rebuild the admin pages so they show operating data rather than endpoint catalogs.

#### Policies page
Show:

- current approval rules
- memory retention mode
- channel permissions
- escalation rules
- recent policy decisions

#### Providers page
Show:

- provider status
- last successful operation
- recent failures
- rate-limit / capacity signals
- configured vs required provider bindings

#### Audit Trail page
Show:

- decision receipts
- delivery confirmations
- evidence attachments
- policy blocks
- actor timeline

#### Team / Operators page
Show:

- active operators
- assignment counts
- overdue approvals
- queue load
- handoff freshness

### Tests

Add tests for:

- operator sees assigned queue only
- principal approval changes draft state
- audit entries exist for every approval or block
- policy settings affect allowed actions in product UI

### Acceptance criteria

- one operator can run the product on behalf of one executive without confusion
- approvals are explainable and auditable
- admin pages help operations instead of merely listing endpoints

---

## Milestone 5 — Compress onboarding into activation

### Goal
Get the customer to value fast.

### Why this matters
A paying customer does not want a careful setup ceremony. They want proof that the assistant can reduce load right away.

### The activation loop to optimize for

1. connect Google
2. generate the first useful brief
3. review one real draft
4. confirm one commitment or follow-up
5. see one audit trail / trust receipt

### Rebuild the onboarding flow

Current state is good directionally, but it still exposes too much too early.

#### New activation structure

##### Screen 1 — Connect account
Only show:

- workspace name
- role: principal or operator
- Google connect CTA

Remove from first-run path:

- messaging choices
- advanced retention settings
- metadata-only channel nuance
- multi-surface explanations

##### Screen 2 — First brief preview
Immediately show:

- top three brief items
- one suggested draft
- one suggested follow-up
- one note about trust / approval posture

##### Screen 3 — Review rules
Only then ask:

- draft approval mode
- send permissions
- retention mode
- optional automation

##### Screen 4 — Add channels later
Move Telegram / WhatsApp to **post-activation settings**, not required onboarding.

### Product copy changes

- replace “setup” language with “activation” language
- stop explaining philosophy where the product can instead demonstrate value
- reduce the volume of explanatory copy on first-run screens by at least half

### Repo changes

- split `get_started.html` into smaller templates or components
- move advanced messaging blocks into settings or channel pages
- add a first-brief preview payload to activation routes

### Acceptance criteria

- a new workspace can reach first useful value without configuring messaging or advanced retention
- the first-run flow proves utility before asking for optional complexity

---

## Milestone 6 — Commercial readiness for a paying customer

### Goal
Make the product operable as something a customer can buy, trust, and renew.

### Why this matters
A good internal demo can still fail as a product if commercial boundaries, usage visibility, and support flows are missing.

### Part A: Packaging and entitlements

The current pricing language is much better, but it is still broad. Turn it into actual entitlements.

Define the unit of sale explicitly. Recommended default:

- one workspace
- one principal
- one operator seat
- one daily memo
- one decision queue
- limited admin access

Then represent that in code.

Add:

- `workspace_plan`
- `plan_entitlements`
- `seat_assignments`
- `feature_flags`

Tie product behavior to entitlements:

- number of operator seats
- messaging channels enabled
- retention modes allowed
- audit retention depth
- advanced admin features

### Part B: Product analytics

Track product value, not just runtime health.

Add event instrumentation for:

- time to first useful brief
- daily memo opened
- queue items resolved
- drafts approved
- drafts rejected
- commitments created
- commitments closed
- memory corrections
- operator handoffs completed

### Part C: Support and diagnostics

Create customer-facing support paths:

- workspace diagnostics page
- exportable audit bundle
- “why did EA suggest this?” receipts
- error messages that explain actionability

### Part D: Billing and commercial admin

Even if you keep billing simple at first, the product should have:

- plan display
- seat display
- renewal owner contact
- basic invoice / billing state visibility
- contract / compliance notes where appropriate

### Acceptance criteria

- the product has a real unit of sale
- feature access can be controlled without code edits
- product usage and product value are measurable
- support can diagnose a customer complaint without reading raw logs first

---

## Milestone 7 — Product-quality QA and release discipline

### Goal
Expand quality gates from runtime correctness into customer workflow correctness.

### Why this matters
The repo already has a good runtime smoke posture. The next step is to verify the actual customer experience.

### Add a product release track
Create a new product release checklist alongside the existing runtime release checklist.

Include:

- activation flow works end-to-end
- first brief renders from fixture data
- one draft can be approved and sent in a staging environment
- one commitment can be closed
- one memory correction can be applied
- one operator handoff can be completed
- one audit bundle can be exported

### Add browser E2E coverage
Introduce a real browser test suite for:

- public landing
- sign-in / identity handoff
- first-run activation
- daily memo view
- draft approval
- commitment closure
- operator handoff
- admin audit inspection

### Add fixture-based product scenarios
Maintain at least three durable fixtures:

1. founder workspace
2. executive + operator workspace
3. shared team workspace

Each fixture should include:

- seeded email threads
- calendar events
- commitments
- draft candidates
- people profiles
- policy state

### Add visual regression for core surfaces
Do not apply this to every page. Apply it only to:

- `/`
- `/get-started`
- `/app/today`
- `/app/briefing`
- `/app/inbox`
- `/app/follow-ups`
- `/admin/audit-trail`

### Acceptance criteria

- runtime smoke stays green
- product browser journeys are tested
- regressions in the daily loop are caught before release

---

## The order to execute these milestones

Do them in this order:

1. **Milestone 0** — product boundary cleanup
2. **Milestone 1** — product objects + product API
3. **Milestone 2** — real daily loop
4. **Milestone 3** — commitments + people graph
5. **Milestone 4** — operator workflow + trust surfaces
6. **Milestone 5** — activation redesign
7. **Milestone 6** — commercial readiness
8. **Milestone 7** — product QA and release track

This ordering matters.

If you do activation or pricing before Milestone 1 and 2, you will package a shell. If you do more design work before Milestone 2 and 3, you will polish placeholders.

---

## Practical repo refactor plan

### Files to keep but narrow

- `ea/app/api/routes/landing.py` → routing/orchestration only
- `ea/app/api/routes/landing_content.py` → marketing content only
- `ea/app/templates/base_public.html` → shared public shell only
- `ea/app/templates/base_console.html` → shared app shell only

### Files to retire or replace

- `ea/app/api/routes/landing_view_models.py` → replace with object-backed product view models
- `ea/app/templates/get_started.html` → split into activation components

### New packages to add

- `ea/app/product/models.py`
- `ea/app/product/api.py`
- `ea/app/product/briefing.py`
- `ea/app/product/queue.py`
- `ea/app/product/commitments.py`
- `ea/app/product/people.py`
- `ea/app/product/handoffs.py`
- `ea/app/product/projections/`
- `ea/app/templates/app/`
- `tests/product/`
- `tests/e2e/`

### New docs to add

- `PRODUCT_BOUNDARY.md`
- `PRODUCT_RELEASE_CHECKLIST.md`
- `CUSTOMER_DIAGNOSTICS.md`
- `FIXTURE_SCENARIOS.md`

---

## Definition of done for the first paying customer

You are ready when all of the following are true:

1. A new customer can connect Google and get a useful brief fast.
2. The morning memo helps them decide what matters today.
3. The draft queue produces at least one review-worthy reply in real use.
4. Commitments are visible, auditable, and closable.
5. The operator can run the system jointly with the principal.
6. Every important suggestion has evidence and an approval posture.
7. Admins can diagnose issues without reading raw internal code first.
8. The product can be packaged, entitled, and supported like a real SaaS or managed deployment.
9. The core daily loop survives releases because it has browser-level tests.

If those are true, the product is no longer just promising. It is useful enough to charge for.

---

## Final recommendation

Do not spend the next cycle on more landing-page work.

Spend it on:

1. product objects
2. decision queue
3. commitment ledger
4. people graph
5. operator handoffs

That is the shortest path from “polished repo” to “product that earns renewal.”
