# Feature and Opportunity Guide for the Chummer6 Developers

## Framing

You did **not** mainly miss “more features.” The repos already contain a huge feature surface: base client capabilities such as NEXUS-PAN, Run Control, Edition Studio, Community Hub, Ghostwire, Local Co-Processor, and Quicksilver; campaign tools such as ALICE, Origin Dossier, Jackpoint, Table Pulse, Karma Forge, Runsite, and Runbook Press; and a long-range roadmap that already names campaign OS, no-step-back parity, Build/Explain leverage, community/world scale, Foundry handoff, Ready for Tonight, role kits, runner passports, and creator systems.

What was missed is **prioritization around felt user value**. The hardening plan makes the release trustworthy; the product plan now needs to make Chummer6 emotionally obvious.

The opportunity is to stop selling “a complete architecture” and start shipping repeatable user moments:

```text
I know what to do before tonight.
I know why this number changed.
I can join without installing everything first.
I can move my runner between communities.
I can hand this to Foundry without copying for an hour.
I can bring my existing campaign in without reconstructing three years of history.
I can trust this creator’s pack.
I can see the world move after the run.
```

Below is the feature/opportunity backlog I would hand to the developers.

---

## 1. Make “Ready for Tonight” the hero feature

### Opportunity

The product should lead with a single anxiety-killing surface: **am I ready for the next session, and what do I fix now?**

The design canon already says `ReadyForTonight` should not be a dashboard; it should be a verdict and action surface that answers whether the user is ready, what blocks them, what changed, and what they should open next. It also defines player, GM, and organizer views, plus an output contract with `status`, `blocking_reasons`, `fix_now_actions`, `changed_since_last_session`, `next_best_screen`, and `proof_receipts`.

### Why this matters

This is the clearest first emotional win in the whole product. Users do not initially care that the architecture has a campaign spine, registry split, media factory, package canon, and proof receipts. They care whether they are ready for game night.

### Build it as

```text
Ready for Tonight
├── Player readiness
│   ├── legal under table rules?
│   ├── injured / broke / over capacity?
│   ├── missing ammo, gear, programs, spells, lifestyle, contacts?
│   ├── what changed since last run?
│   └── make me ready for this run
├── GM readiness
│   ├── roster complete?
│   ├── blocked runners?
│   ├── missing prep packet / opposition / handouts?
│   ├── unresolved rewards, debts, injuries, favors?
│   └── export tonight pack
└── Organizer readiness
    ├── run publishable?
    ├── safety and consent gates satisfied?
    ├── meeting handoff configured?
    ├── beginner path available?
    └── moderation/support risks clear?
```

### Acceptance test

```text
A new or returning user can open Chummer and answer “what do I need to do before tonight?” in under 60 seconds.
```

### Developer instruction

Do not make this a generic dashboard. It should return a verdict, one prioritized blocker, and one next action.

---

## 2. Build a no-desktop onboarding path

### Opportunity

The desktop can remain the expert flagship, but public scale is capped if every new participant must install a desktop app before they understand whether they can join.

The design canon already says no-desktop users must be able to discover whether they are welcome, choose a beginner-safe path, and join a run without being blocked before they understand the table. The required capabilities include mobile-readable open run listings, quickstart runner selection, application preflight, table contract acknowledgement, meeting handoff, recap receipt, and the `make me ready` verdict.

### Why this matters

This is a growth feature, not a convenience feature. It turns Chummer6 from “a tool existing players install” into “a doorway for people to enter organized Shadowrun play.”

### Build it as

```text
Public run page
-> table contract
-> rule environment summary
-> quickstart runner or approved runner
-> application preflight
-> meeting handoff
-> session participation
-> recap and next-step guidance
```

### Non-goal

Do not make web/mobile replace the desktop lane. The design canon explicitly says no-desktop participation must not pretend to replace the flagship desktop or force full character-building before first participation.

### Acceptance test

```text
A beginner can determine whether they can join a beginner run in minutes without installing the Windows desktop client.
```

---

## 3. Turn role kits into the beginner-build engine

### Opportunity

Shadowrun character creation creates gear paralysis. Chummer6 can win trust by giving users governed starter loadouts that remain rule-environment aware and explainable.

The design canon says role kits are not flavor bundles; they are governed starter decisions that reduce cognitive load while staying explainable and rule-environment aware. It names initial kits: street samurai, face, mage, decker, rigger, and general survivor.

### Build it as

```text
Role Kit
├── role intent
├── minimum viable gear
├── optional upgrades
├── active ruleset legality
├── why each item exists
├── what is still missing for this run
└── safe swaps
```

### Connect it to

The canon already says role kits should feed ONRAMP, quickstart runners, Build Lab, Ready for Tonight, and open-run application preflight.

### Acceptance test

```text
A new player can create or select a table-legal quickstart runner and understand why the core gear is present.
```

### Developer instruction

Every kit recommendation must be explainable. The kit should answer “why was this recommended,” “what rule environment shaped it,” “what would make this illegal,” and “what can I safely swap.”

---

## 4. Promote source-aware explain as the signature trust feature

### Opportunity

“Why is this number what it is?” should become Chummer6’s strongest differentiator.

The design canon already frames source-aware explain as a public trust promise. When users ask why a value is what it is, Chummer should answer from governed truth and, when locally available, open the bound rulebook to the relevant page.

### Why this matters

This is not just a nice inspector. It reduces rules anxiety, helps new players trust recommendations, helps GMs settle disputes, and makes house-rule/amend-package diffs more believable.

### Build it as

```text
visible value
-> explain drawer
-> modifier chain
-> source anchor
-> local rulebook page, if available
-> why / why not / what if follow-up
```

### Critical boundary

The canon already states no cloud rulebook upload is required and no raw local path enters telemetry. Preserve that. This is a local-trust feature, not a cloud-content ingestion feature.

### Acceptance test

```text
Every flagship-visible mechanical value either opens packet-backed explain + source anchor or appears in a release-blocking gap list.
```

---

## 5. Ship one excellent VTT handoff, not five weak integrations

### Opportunity

Pick one VTT target and make it excellent. The canon already identifies a **Foundry-first VTT handoff proof** and explicitly says the first external play-surface proof should be Foundry-class export quality good enough to stop hand-copying for one real table.

### Build it as

```text
one runner
+ one opposition packet
+ one player-safe handout
+ one export receipt
= one Foundry-ready handoff package
```

The design canon names exactly that first proof package.

### Why this matters

VTT export is an adoption accelerator. It lets GMs feel the value immediately because they stop copying character and opposition details by hand.

### Non-goals

Do not support every VTT in wave one. The canon explicitly says Foundry-first is not equal support for every VTT, not making Foundry canonical, and not treating export success as proof the run itself is canonical there.

### Acceptance test

```text
A GM can export one runner, one opposition packet, and one player-safe handout to Foundry-class JSON/package format and use it at a real table without manual re-entry.
```

---

## 6. Add “start from today” campaign adoption

### Opportunity

Existing groups should not need to reconstruct an entire campaign history before Chummer becomes useful.

The canon already says Chummer should let a table start from current truth, mark unknown history explicitly, and clean it up later. The core flow is: enter/import current runners, mark partial history, bind rule environment, record debts/favors/contacts/active jobs, receive adoption confidence, and start the ledger from today.

### Build it as

```text
Campaign Adoption Wizard
├── import or enter current runners
├── bind current rule environment
├── mark unknown history
├── enter active jobs / debts / favors / contacts
├── flag unresolved review items
├── generate adoption confidence
└── create replay-safe start anchor
```

### Public promise

Use the canon’s plain-language promise:

```text
start from today
keep what you already know
mark what you do not know
let future receipts become clean
```

### Acceptance test

```text
A GM with an existing campaign can onboard the table in one sitting without reconstructing old session history.
```

---

## 7. Build Runner Passport as a portability wedge

### Opportunity

A portable runner trust object can become the backbone for community play, open-run applications, and cross-table trust.

The canon defines `RunnerPassport` as the smallest portable trust object that lets a runner move between tables and communities without restarting the entire approval story. It says communities need to know whether the runner is legal under a named rule environment, reviewed under a community posture, carrying unresolved conflicts, and suitable for a specific open run or season.

### Build it as

```text
Runner Passport
├── runner identity ref
├── ruleset and rule-environment fingerprint
├── approval state
├── review timestamp and reviewer role
├── unresolved warnings
├── quickstart vs full-dossier posture
├── export/play-surface eligibility
└── bounded validity window
```

Those are already the required fields in canon.

### Critical boundary

Do not turn this into a social credit system. The canon explicitly says the passport is not a permanent social score; it is scoped trust and compatibility proof for a governed table/community lane.

### Acceptance test

```text
A runner approved in one governed community can apply to another compatible table with a passport instead of resubmitting the full approval story.
```

---

## 8. Turn creator publication into a creator operating system

### Opportunity

Publishing alone is not enough. Creators need to know whether their work is compatible, adopted, healthy, moderated, and worth updating.

The canon says creator publication should become a live operating system instead of a static artifact shelf. Creators should be able to learn whether their work is compatible, adopted, healthy, and worth updating.

### Build it as

```text
Creator Dashboard
├── publication status
├── compatibility posture
├── breakage posture
├── adoption band
├── moderation and trust state
├── update requests
├── support issues
├── promo readiness
└── approved-source media packet
```

These surfaces are already listed in the canon.

### Why this matters

If creators cannot tell whether their work is compatible and adopted, publication becomes a graveyard instead of an ecosystem. The canon says this directly.

### Acceptance test

```text
A creator can publish, see whether the package is compatible with current release truth, see adoption band, receive breakage/update requests, and prepare a safe promo packet.
```

---

## 9. Build community safety before public scale

### Opportunity

Open runs and public communities need governance for bad cases, not just happy-path participation.

The canon already says public open-run scale requires a safety and trust lane. It names event families such as no-show/abandonment, unsafe content, harassment, spoiler leaks, application disputes, GM trust escalation, leaderboard gaming, and observer-consent violations.

### Build it as

```text
Community Safety Lane
├── report intake
├── triage
├── evidence posture
├── temporary action
├── final decision
├── appeal route
├── retention posture
└── publication posture
```

Those are also already required states in canon.

### Critical boundary

Do not make this punitive theater. The canon says safety tooling exists to make public and community play sustainable and trustworthy.

### Acceptance test

```text
A public-run incident can be reported, triaged, decided, appealed, retained, and bounded without exposing private campaign/player internals.
```

---

## 10. Add weekly world dispatch and reactivation loops

### Opportunity

The product should pull users back because the world moved, not because of generic notifications.

The canon defines a World Dispatch and Reactivation Loop: the world should talk back on a cadence, reactivating players, GMs, and communities through receipt-backed consequence rather than generic marketing copy.

### Build it as

```text
Weekly Dispatch Bundle
├── city or campaign ticker
├── faction or world spin item
├── GM-only job/consequence digest
├── player-safe “what changed for me” card
└── optional recruitment or return prompt
```

That weekly bundle is already described in canon.

### Why this matters

A user should miss Chummer when they skip a week because the world moved, their crew state changed, a hook became actionable, or the next useful action is obvious.

### Acceptance test

```text
After a run closes, Chummer emits one player-safe change card, one GM-only consequence digest, and one public-safe return prompt from approved campaign/world truth.
```

---

## 11. Productize “Quicksilver” for expert speed

### Opportunity

The feature list names Quicksilver as expert-speed jumps across builds, rules, prep, and publication desks without leaving Chummer. This could become the power-user signature for veteran Chummer5a users.

### Build it as

```text
Command palette
├── jump to runner
├── jump to rule
├── jump to source anchor
├── compare two builds
├── open Ready for Tonight blocker
├── export current packet
├── create GM handout
├── open last changed value
├── open active rule environment diff
└── open support packet for current error
```

### Acceptance test

```text
A veteran user can complete the top 20 repeated Chummer5a-style navigation tasks without mouse travel through nested screens.
```

### Why this matters

This is how the product wins veteran trust without sacrificing beginner onboarding.

---

## 12. Make Local Co-Processor a privacy-preserving performance story

### Opportunity

The feature list already names Local Co-Processor as optional local acceleration without turning the product into a black box. That can become both a performance and privacy differentiator.

### Build it as

```text
Local Co-Processor
├── local explain cache
├── local rulebook source anchors
├── local search index
├── local import/migration preview
├── local “why changed” diff cache
├── no cloud upload for rulebooks
└── visible privacy boundary
```

### Acceptance test

```text
A user can enable local acceleration and see exactly what stays local, what is cached, what is never uploaded, and what can be deleted.
```

---

## 13. Create a “one-table starter campaign” bundle

### Opportunity

The docs contain role kits, no-desktop onboarding, Ready for Tonight, VTT handoff, and campaign adoption. The missing feature that connects them is a **starter campaign bundle**.

This is not just a sample adventure. It should be a complete proof that the product can take a table from zero to first recurring session.

### Build it as

```text
Starter Campaign Bundle
├── one beginner-safe run
├── six role-kit runners
├── one GM prep packet
├── one Foundry export package
├── one Ready for Tonight checklist
├── one recap template
├── one consequence/dispatch example
└── one support-safe demo data set
```

### Acceptance test

```text
A new GM can run a starter session using only the bundle and Chummer6’s guided flow.
```

### Why this matters

This is the fastest way to demonstrate the entire product loop without asking users to imagine the architecture.

---

## 14. Build “table contract” as a first-class object

### Opportunity

Several planned features imply a table contract: no-desktop onboarding, open-run preflight, runner passport, community trust, safety/moderation, and Ready for Tonight. But “table contract” should become a first-class artifact.

### Build it as

```text
Table Contract
├── ruleset
├── rule environment fingerprint
├── books/sources allowed
├── house rules
├── content/safety posture
├── attendance expectations
├── character approval rules
├── import/export policy
├── VTT/platform handoff
└── dispute/appeal route
```

### Acceptance test

```text
Every open run and campaign has a table contract that feeds application preflight, runner passport validation, Ready for Tonight, and moderation posture.
```

---

## 15. Add “what changed?” as a universal product pattern

### Opportunity

The README already says Chummer6 exists for the moment someone asks “why did that number change?” and the table deserves better than memory. That idea should become a universal UI pattern, not just explain math.

### Build it as

```text
What Changed?
├── character values
├── gear legality
├── rule environment
├── session state
├── debts/favors/contacts
├── campaign memory
├── install/update state
├── source package revisions
└── creator package compatibility
```

### Acceptance test

```text
Every major state transition can show before, after, cause, source, and next safe action.
```

---

## Suggested Opportunity Backlog

## P0: First emotional win

- [ ] Ready for Tonight Mode
- [ ] Role Kits / Starter Loadouts
- [ ] Source-Aware Explain proof
- [ ] No-desktop beginner participation path
- [ ] “What changed?” universal pattern

## P1: Adoption and table utility

- [ ] Foundry-first VTT handoff
- [ ] Start-from-today campaign adoption
- [ ] Table Contract object
- [ ] Starter Campaign Bundle
- [ ] Quicksilver expert navigation

## P2: Community and ecosystem

- [ ] Runner Passport
- [ ] Creator Operating System
- [ ] Community Safety / Moderation / Appeals
- [ ] Weekly World Dispatch
- [ ] Creator adoption analytics

## P3: Strategic differentiators

- [ ] Local Co-Processor privacy/performance story
- [ ] Rulebook source-anchor trust layer
- [ ] Cross-community runner portability
- [ ] Campaign memory reactivation loops
- [ ] Public proof/demo shelf for real table workflows

---

## The most important product bet

The strongest missed opportunity is not one feature. It is this integrated loop:

```text
No-desktop user finds a public run
-> chooses a role kit
-> passes table-contract preflight
-> receives Ready for Tonight verdict
-> plays
-> gets recap and “what changed for me”
-> receives Runner Passport update
-> sees world dispatch next week
-> returns
```

That loop ties together onboarding, rules trust, campaign continuity, community trust, and reactivation. It makes Chummer6 feel like a living table operating system instead of a powerful but intimidating builder.
