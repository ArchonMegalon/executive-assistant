# TABLE PULSE

Table Pulse has two rails. The design only works if those rails stay explicit.

**Table Pulse Live** is the GM-controlled heat and reaction rail. During a session or in the
immediate aftermath of a session, security, matrix, magic, astral, faction, law, media, or public
pressure can cross a threshold. If the GM allows it, Chummer can notify eligible players or
faction contacts, let them play a bounded reaction mini-game, and return the result to the GM for
approval.

**Table Pulse Aftermath** is the private coaching rail. After a session, the GM can review pacing,
spotlight balance, confusion points, disengagement markers, and follow-up suggestions without
turning Chummer into surveillance or player scoring.

The live rail and the coaching rail may share receipts, mute controls, and GM policy, but they are
not the same product promise and should not be described as if they are one heat system.

## The problem

The GM needs two different things:

* a live or near-live pressure rail that can surface in-world heat without auto-mutating canon
* a private aftermath rail that can help explain where pacing, spotlight, or confusion drifted

Those are different kinds of heat. If the page collapses them into one concept, the design becomes
muddy and reads like surveillance plus mini-games instead of two bounded product rails.

## The two rails

### Table Pulse Live

TABLE PULSE LIVE is the in-world command and reaction layer.

It covers:

* world heat domains and threshold events
* recipient decision packets
* GM pulse policy
* player-safe delivery, mute controls, and consent posture
* remote reaction mini-games
* governed BLACK LEDGER aftermath projection

Its job is to let heat cross a threshold, produce a packet, and return a bounded result to the GM.
It is not automatic table mutation.

### Table Pulse Aftermath

TABLE PULSE AFTERMATH is the private coaching and recap layer.

It covers:

* pacing heat
* spotlight imbalance
* interruption or confusion spikes
* disengagement markers
* optional narrated summaries
* follow-up suggestions for the next run

Its job is to help the GM reflect after play. It is not a live command surface, public scoreboard,
or moderation truth system.

## What is live now

The whole coaching and observer stack is not universally shipped.

What is live today is Table Pulse Live on the signed-in command lane:

* a Table Pulse packet on the Black Ledger notifications route
* bounded remote reaction mini-games
* GM adjudication and leader follow-through
* Signal Deck and Runner Passport continuity
* Living Newsroom watch framing
* governed aftermath return loops

So the command-to-fallout loop is real now, while Table Pulse Aftermath and the broader coaching,
transcript, and narrated-summary stack remain future-facing, consent-bounded, and explicitly
non-authoritative.

## What players and remote users would actually see

The first public-safe version is not a giant dashboard. It is a handful of sharp bounded moments:

* a packet that says a scene generated heat
* a reason why this player or faction contact received the packet
* one or two choices that can move pressure, rumor, or favor
* a receipt that shows whether the GM still must approve fallout

Remote users would only see packets they are explicitly allowed to see under campaign policy,
quiet hours, and recipient rules.

## Heat vocabulary

TABLE PULSE uses two different heat vocabularies and should say so plainly.

### World heat

World heat belongs to Table Pulse Live.

Examples:

* security pressure
* matrix pressure
* magic or astral pressure
* faction pressure
* law, media, or public pressure

World heat can produce a packet, a bounded remote reaction, and a GM adjudication choice.

### Table-dynamics heat

Table-dynamics heat belongs to Table Pulse Aftermath.

Examples:

* pacing drag
* spotlight imbalance
* interruption spikes
* confusion points
* disengagement markers

Table-dynamics heat is private GM coaching, not in-world pressure truth.

## Heat and reaction model

TABLE PULSE LIVE treats world heat as a governed pressure signal, not generic drama text.

Examples:

* faction or public pressure after a noisy result
* security pressure around a research breach
* matrix pressure after a loud hack
* magic or astral pressure after an awakened spike
* consequence pressure that can spill into BLACK LEDGER

Heat does not mutate table truth by itself. It creates a bounded packet that a GM can inspect,
route, suppress, or turn into a follow-up action.

## Remote reaction mini-games

The most exciting outside-the-session lane is the remote reaction mini-game family.

Core examples:

* **Intercept** - catch, forward, or suppress a courier or intel lane
* **Cover Story** - shape the cleanup narrative after a messy outcome
* **Scramble** - spend time, favor, or logistics to preserve an asset
* **Temptation** - accept a risky offer that increases pressure for a later edge
* **Shadow Reply** - send back a coded answer that changes rumor, order, or Passport flavor

These are:

* opt-in or policy-allowed
* receipt-backed
* bounded in consequence
* safe to adjudicate outside the main session

They are not:

* direct mutation of live table canon
* autonomous side campaigns
* public scoreboards
* a replacement for the GM

## Table Pulse Aftermath boundaries

TABLE PULSE AFTERMATH is explicitly:

* GM-private
* opt-in
* consent-bounded
* not surveillance
* not player scoring
* not public trust or moderation truth

It may eventually widen into transcript structure, narrated recap, or highlight support, but only
after privacy, retention, receipt, and adjudication proof are complete.

## Likely owners

* `chummer6-hub`
* `chummer6-media-factory`

## Key tool posture

* `Nonverbia` - primary coaching and social-dynamics analysis lane
* `hedy.ai` - bounded transcript structure, highlight digest, and GM debrief prompt lane
* `vidBoard` - later bounded player-safe recap and GM-private debrief video lane
* `Soundmadeseen` - optional narrated coaching summary
* `Unmixr AI` - bounded candidate voice lane until proven
* `MarkupGo` - coaching packet render support
* `PeekShot` - preview/share-safe summary card support

See also: `HEDY_AI_TABLE_PULSE_DESIGN.md`

## What has to be true first

* explicit consent and upload policy
* post-session-only analysis and packet rules
* privacy and retention rules for coaching media
* share-safe coaching summaries
* replay and receipt references where available
* mute, suppression, and quiet-hours proof
* GM adjudication for outside reactions

## Hard boundary

* Table Pulse Live is not automatic world authority
* not live surveillance
* not player scoring
* not moderation truth
* not discipline automation
* not canonical session truth

## Why it is not ready yet

This only works if the two rails stay separate:

* Table Pulse Live must remain GM-controlled, receipt-backed, and fail-closed
* Table Pulse Aftermath must remain private, consent-bounded, and clearly separate from moderation
  or rules truth

Until Chummer can prove those guardrails end to end, TABLE PULSE remains a split horizon page with
one live rail and one future-facing rail rather than a claim that the full coaching, transcript,
remote-user, and mini-game stack is already universally shipped.
