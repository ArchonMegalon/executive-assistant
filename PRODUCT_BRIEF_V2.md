# Executive Assistant Product Brief v2

## Product promise

Executive Assistant is the operating system for one executive office.

The product exists to protect executive attention and close commitments.

The first wedge is intentionally narrow:

- one executive
- one operator
- one communication core
- one daily memo
- one decision queue
- one commitment system

## Core objects

Everything in the product should reduce to a small set of objects:

- `people`
- `threads`
- `commitments`
- `decisions`
- `drafts`
- `evidence`
- `rules`

Channels feed these objects. They do not replace them.

## Primary surfaces

### 1. Morning memo

The morning memo answers:

- what changed since yesterday
- what now threatens the calendar
- which stakeholders need a response
- which commitments are aging badly
- which decisions are blocked

### 2. Decision queue

Every item in the queue is one of:

- approve draft
- choose between options
- confirm memory change
- assign owner
- defer
- close commitment

### 3. Commitment ledger

Messages, meetings, and notes are not the product center.

They matter only when they:

- create a commitment
- update a commitment
- require a decision
- produce a draft
- enrich stakeholder context

### 4. People graph

The people graph keeps:

- stakeholder importance
- relationship temperature
- open loops
- latest commitments
- recurring themes
- risk signals
- preferred tone and cadence

### 5. Handoffs

The product supports office workflow, not just one user with an assistant:

- principal
- operator / chief of staff / executive assistant
- optional reviewer
- admin

### 6. Rules

Rules are first-class product behavior:

- what the assistant may read
- what it may draft
- what it may send
- what it may remember
- what needs approval
- which channels may influence the memo

## Product shape

The center of gravity is not the dashboard.

The executive should mostly experience the system through:

- morning memo delivery
- inline approvals
- draft review
- follow-up reminders
- handoff summaries

The web app exists mainly for:

- deep review
- memory inspection
- policy control
- operator collaboration
- audit and history

## Day-one boundary

Ship less:

- Gmail
- Calendar
- one morning memo
- one decision queue
- one commitment ledger
- one people graph
- approvals
- audit trail

Do not make side surfaces part of the core product story.

## Architecture direction

Keep three layers explicit:

1. `core runtime`
   - FastAPI
   - workers
   - queue
   - memory
   - evidence
   - policies
   - tools
   - delivery

2. `product API / BFF`
   - commitments
   - drafts
   - people
   - decisions
   - brief items

3. `client surfaces`
   - web console
   - email output
   - mobile/chat approvals

The browser product should become a thin consumer of product-level objects instead of assembling a polished shell around onboarding and helper copy.

## GTM wedge

Sell one thing first:

`the operating system for one executive and one operator`

That means:

- one principal
- one operator
- one decision queue
- one commitment graph
- one daily memo

Expand only after that loop is undeniable.
