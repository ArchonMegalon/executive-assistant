# Updated LTD utilization opportunities for Chummer6 + Executive Assistant

## Executive verdict

The updated LTD inventory is no longer just a vendor list. It now documents a usable operating substrate: **55 tracked LTD products**, with explicit workspace tiers, large restored runtime capacity, Tier 1 operator infrastructure, and several gated provider lanes. The file's own tier model says Tier 1 means "actively wired into the local workspace/runtime and ready for operational use," while Tier 2 means owned and partially wired or intentionally parked.

The biggest changes versus the earlier read are:

1. `1min.AI` is now a serious background-capacity pool, not just one AI provider. It has 12 licenses, 12 accounts, 74 restored runtime slots, 71 populated API-key entries, and a routing decision to prefer 1min background work when usable.

2. `Teable` moved into Tier 1 operational infrastructure. It now has local API key/table IDs, proactive OODA and WhatsApp sync flags, projection adapters, and a recovery-readiness receipt, with only a fresh-host drill still pending.

3. `vexp.dev` is new Tier 1 cross-repo infrastructure. It has an active license, activated CLI, Codex MCP stanza pinned to `/docker/EA`, and a healthy cross-repo workspace index.

4. `OMagic` is newly tracked as a 9-account user-reported holding, but no OMagic-specific credentials or runtime slots were found in the restored env/config set, so it is inventory opportunity rather than live capacity.

5. `AI Magicx` is now clearly staged, not verified live. It has routing and health-check plumbing, but the current `.env` still has an empty API key.

6. The portfolio now has multiple high-capacity pools: `1min.AI`, `MagicFit`, `OMagic`, `Unmixr AI`, and `YouBooks` are explicitly listed as multiple-account or multiple-slot holdings.

The missed opportunity is now sharper: you should not merely "use LTDs"; you should make them a governed execution fabric behind Chummer6, EA, Fleet, and Black Ledger.

---

## 1. Build an LTD Capacity Scheduler, not just a capability router

The earlier recommendation was "build an LTD capability router." With the updated file, that is no longer enough.

`1min.AI` now has restored multi-slot capacity and live operator status showing very large remaining credits, many configured slots, and a background-routing preference. That creates a new opportunity: a capacity-aware background scheduler.

### Build this

Create:

```text
executive-assistant/config/ltd_capacity_scheduler.yaml
executive-assistant/scripts/materialize_ltd_capacity_status.py
executive-assistant/scripts/verify_ltd_capacity_scheduler.py
```

### What it should do

The scheduler should route work based on:

```text
provider capability
credit balance
slot health
latency class
privacy class
human-review requirement
cost/credit pressure
fallback availability
```

### First use cases

```text
1min.AI:
  use_for:
    - background summarization
    - low-risk draft generation
    - batch public-doc transformation
    - low-priority support-draft expansion
    - media prompt variants
    - Black Ledger script alternatives
  avoid_for:
    - release truth
    - rules truth
    - private campaign data
    - entitlement truth
```

### Why this matters

The restored `1min.AI` pool is large enough to treat as a background compute lane. That means EA can queue non-urgent work instead of burning premium model calls or blocking interactive flows.

### Acceptance test

```text
Given 100 queued low-risk public-content tasks, EA routes them through 1min.AI background capacity, records provider/slot/credit receipt, and falls back only when slot health or policy blocks the route.
```

---

## 2. Use Teable as the live LTD/product operations cockpit

Previously, Teable looked like a projection surface. Now it is Tier 1, with local API key, table IDs, proactive OODA sync, WhatsApp sync flags, and projection adapters.

That means Teable should become the operations cockpit for LTD utilization, not just another table mirror.

### Build this

Create Teable bases/tables for:

```text
LTD Provider Status
LTD Proof Debt
Release Trust Factory
Black Ledger Production Queue
Creator Publication Health
Support/Concierge Signals
Outbound Growth Approvals
Public Feedback / Roadmap Signals
Media Provider Bake-Off Results
```

### Minimum table schema

```text
provider
workspace_tier
runtime_status
next_required_proof
allowed_input_classes
forbidden_input_classes
owner
last_receipt
last_success
last_failure
promotion_target
blast_radius
human_review_required
```

### Why this matters

The LTD portfolio now has too many candidate lanes to manage in prose. Teable should become the live operator view that says:

```text
What can I use today?
What is blocked?
What proof is missing?
What is overused?
What is unsafe to promote?
```

### Acceptance test

```text
Every LTD row with Tier 1 or Tier 2 status appears in Teable with current provider status, next proof, allowed uses, and blocking risks.
```

---

## 3. Use vexp.dev as the cross-repo opportunity index

`vexp.dev` is the most important new entry. It is Tier 1, has an active local license, activated CLI, a managed Codex MCP stanza, and a healthy cross-repo index over the shared workspace.

That creates a new opportunity: make vexp the semantic index that finds where an LTD can attach to product work.

### Build this

Create:

```text
executive-assistant/docs/VEXP_LTD_OPPORTUNITY_INDEX.md
executive-assistant/scripts/query_ltd_opportunity_index.py
```

### Example queries

```text
Which Chummer6 docs mention Black Ledger but have no media provider mapped?
Which scripts produce release receipts but do not publish to Teable?
Which support surfaces could use Answerly or Emailit?
Which docs mention Foundry handoff but lack FlipLink/MarkupGo public artifacts?
Which campaign-memory surfaces could emit Unmixr audio?
Which provider lanes are mentioned in docs but not in LTDs.md?
```

### Product impact

This turns vexp into a cross-repo "missed opportunity detector." It can connect:

```text
repo docs
scripts
receipts
public guide pages
roadmap items
LTD inventory
provider boundaries
```

### Acceptance test

```text
A weekly vexp-backed report lists the top 20 unclaimed product opportunities where an existing LTD can reduce cost, accelerate proof, or improve user-facing polish.
```

---

## 4. Add LTD proof debt as a first-class release/readiness metric

The updated file now explicitly calls out attention items: `katteb.com` needs redemption/activation verification, Pixefy and Rafter are auxiliary QA gates, MagicFit has additional accounts needing account-use receipts, Subscribr remains draft/operator only, and YouBooks needs provider-specific integration contracts and verification receipts.

That should become a machine-readable proof-debt register.

### Build this

Create:

```text
executive-assistant/.codex-studio/published/LTD_PROOF_DEBT.generated.json
```

### Example rows

```json
{
  "service": "MagicFit",
  "currentTier": 4,
  "targetTier": 2,
  "nextProof": "account-use receipt for shared/media accounts",
  "candidateLane": "Black Ledger B-roll and Chummer promo recovery",
  "mustNotClaim": [
    "runtime production lane",
    "produced public asset from unverified accounts"
  ]
}
```

```json
{
  "service": "Subscribr",
  "currentTier": 4,
  "targetTier": 2,
  "nextProof": "API/channel/export/source-binding/human-review receipts",
  "candidateLane": "Chummer and Black Ledger video pre-production",
  "mustNotClaim": [
    "publication approval",
    "rules interpretation",
    "release truth"
  ]
}
```

### Acceptance test

```text
Every Tier 2-4 LTD has exactly one next-proof item, one candidate lane, and one explicit "must not claim" boundary.
```

---

## 5. Promote "background OODA loop" as an EA product feature

The updated Teable entry says proactive OODA sync and WhatsApp Web Teable sync flags are enabled locally. This is bigger than a sync detail. It suggests a product feature: EA runs a background OODA loop over signals, decisions, queues, and provider states.

### Build this

```text
EA Background OODA Loop
├── Observe
│   ├── release drift
│   ├── provider health
│   ├── support signals
│   ├── public feedback
│   ├── missed deadlines
│   └── stale receipts
├── Orient
│   ├── classify risk
│   ├── map to owner
│   ├── map LTD lane
│   └── detect missing proof
├── Decide
│   ├── create decision packet
│   ├── request approval when needed
│   └── assign next action
└── Act
    ├── update Teable projection
    ├── draft email or approval packet
    ├── create receipt
    └── notify operator
```

### LTDs involved

```text
Teable: live projection
1min.AI: low-risk background drafting/summarization
Rafter: false-complete/security check
BrowserAct: route/account/provider proof
Emailit: approved notification
ApproveThis: external approval transport
blipai: operator voice/audit note capture
```

### Acceptance test

```text
A stale release-truth receipt triggers an OODA item, maps to owner and provider lane, appears in Teable, and produces an approval-ready decision packet without sending or publishing automatically.
```

---

## 6. Build an LTD blast-radius classifier

The updated inventory contains many explicit boundaries: tools must not own truth, publish directly, process private data, or bypass approval. Those boundaries need to become a classifier.

### Build this

Create:

```text
executive-assistant/config/ltd_blast_radius.yaml
```

### Classes

```yaml
public_safe:
  examples:
    - public release copy
    - public docs
    - approved marketing copy

operator_internal:
  examples:
    - internal memo
    - proof debt dashboard
    - audit note

private_sensitive:
  examples:
    - support ticket
    - private campaign data
    - Gmail/Calendar
    - people memory
    - secrets

regulated_or_high_risk:
  examples:
    - billing
    - entitlement
    - account access
    - release promotion
    - publication approval
```

### Provider policy examples

```yaml
Poppy AI:
  max_input_class: public_safe
  may_publish: false
  may_own_truth: false

Sendr:
  max_input_class: approved_outreach_packet
  may_send_directly: false
  requires_human_approval: true

Answerly:
  max_input_class: support_safe_redacted
  may_answer_rules_truth: false
```

### Why this matters

The inventory now has enough active and staged providers that accidental misuse becomes a real risk. Blast-radius classification keeps the LTD mesh safe.

---

## 7. Exploit OMagic only after account discovery

`OMagic` is new and potentially valuable: 9 user-reported accounts. But the file says no OMagic-specific credentials or slots surfaced in the restored environment/config set.

### Opportunity

Treat OMagic as a capacity-discovery sprint, not a product lane yet.

### Build this

```text
OMagic Discovery Sprint
├── BrowserAct account discovery
├── plan/tier verification
├── capability inventory
├── API/export check
├── commercial-use check
├── privacy boundary
├── candidate lane mapping
└── first smoke proof
```

### Candidate lanes after verification

Depending on capabilities:

```text
visual drafts
video drafts
prompt generation
marketing copy drafts
Black Ledger candidate assets
release explainer variants
```

### Acceptance test

```text
OMagic is not listed in any runtime router until account capability and at least one smoke proof are captured.
```

---

## 8. Turn AI Magicx into a true secondary-provider lane or retire it

The updated row says AI Magicx has runtime routing and health checks, but the current key slot is empty, so it remains staged.

### Opportunity

Treat AI Magicx as a controlled interactive overflow lane distinct from 1min's background lane.

### Decision needed

Choose one:

```text
A. Promote AI Magicx:
   - fill key
   - run health proof
   - define allowed task classes
   - add routing threshold

B. Retire/park AI Magicx:
   - keep inventory
   - remove from runtime fallback selectors
   - prevent false confidence
```

### Suggested role if promoted

```text
AI Magicx:
  use_for:
    - short interactive overflow
    - audit-support drafts
    - alternate phrasing
    - fast low-risk assistant replies
  not_for:
    - bulk background jobs
    - private data
    - release/rules/support truth
```

### Acceptance test

```text
Runtime selectors must not route to AI Magicx when `AI_MAGICX_API_KEY` is empty.
```

---

## 9. Convert 1min.AI + vexp.dev into a cross-repo janitor swarm

This is the strongest new operational opportunity.

You now have:

* Huge 1min background capacity.
* vexp cross-repo semantic indexing.
* Teable operational projection.

### Build this

```text
Cross-Repo Janitor Swarm
├── vexp finds drift
├── 1min drafts low-risk fixes/reports
├── Teable tracks queue and owners
├── Rafter checks false-green/security risks
├── BrowserAct validates public routes
└── human approves mutation
```

### Good janitor tasks

```text
stale docs
broken links
missing citations
release-hash mismatches
orphan proof receipts
duplicate generated files
provider boundary drift
missing "do not claim" text
unverified LTD lane references
public guide / registry mismatch
```

### Boundary

Do not let the swarm commit directly to release truth. It can draft patches and proof reports. Human/CI approval remains required.

### Acceptance test

```text
A weekly janitor run finds at least one stale proof or documentation drift, files a Teable row, drafts a patch/report, and marks it "requires human approval."
```

---

## 10. Use Teable + ProductLift + MetaSurvey as a public signal stack

ProductLift remains the public signal mirror for feedback, voting, roadmap, changelog, package follow, and Karma Forge signal projection. MetaSurvey has staged feedback extraction support. Teable is now Tier 1 and operational.

Updated opportunity:

Make a full signal stack:

```text
ProductLift: public signal mirror
MetaSurvey: structured user survey / onboarding survey
Teable: operator triage and OODA dashboard
EA: canonical decision packet
ApproveThis: external approval if needed
Emailit: approved response/follow-up
```

### First Chummer use cases

```text
Which platform do users need next?
Which installer failed?
Which feature blocks first session?
Which role kit do new users choose?
Which Foundry export fields are missing?
Which Black Ledger episode worked?
```

### Acceptance test

```text
A user feedback item moves from public signal -> Teable triage -> EA decision packet -> public changelog response without ProductLift or MetaSurvey owning roadmap truth.
```

---

## 11. Make YouBooks a discovery lane, not a product lane

YouBooks now has five locally seeded accounts, but still lacks provider-specific integration contract and verification receipts.

### Opportunity

Treat YouBooks as a potential approved-source transformation or book-production lane, but do not use it until verified.

### Candidate uses after proof

```text
public guide booklet drafting
release explainer booklet
starter campaign booklet
creator handbook
GM Foundry handoff guide
Black Ledger primer
```

### Required proof before use

```text
account capability receipt
export format receipt
copyright/privacy boundary
source-packet input validation
no private/sourcebook text rule
human review
```

### Acceptance test

```text
No Chummer/EA source packet is sent to YouBooks until provider contract and account capability receipts pass.
```

---

## 12. Upgrade Black Ledger production: Subscribr + Syllabbles + Unmixr + MagicFit + Pixefy + Emailit

The updated file confirms:

* Subscribr is a high-capacity script-intelligence lane, but still draft/operator only until verification.
* Syllabbles is a Black Ledger dispatch draft workbench only.
* Unmixr has direct narration wiring, multiple capacity slots, and voice roundtrip receipts.
* MagicFit has candidate video/B-roll value but needs provider/account-use receipts.
* Pixefy has verified responsive visual QA.
* Emailit is already the approved Black Ledger delivery lane after episode proof.

### Build this

```text
Black Ledger Production Line
├── approved source packet from Chummer/EA
├── script draft from Subscribr or Syllabbles
├── narration from Unmixr
├── B-roll candidate from MagicFit
├── visual QA from Pixefy
├── route/provider proof from BrowserAct
├── editorial approval in EA
└── delivery through Emailit
```

### Acceptance test

```text
One Black Ledger episode can move from approved source packet to script, narration, candidate visuals, QA, human approval, and email delivery without any provider owning editorial truth or publishing directly.
```

---

## 13. Use Rafter as a false-complete gate across all LTD lanes

Rafter is now explicitly release-security and false-complete prevention infrastructure, with targets including approval bypass, outbound-send authorization, cross-principal isolation, expired-link handling, callback validation, secret leakage, and false-green receipts.

### Missed opportunity

Do not use Rafter only for release security. Use it as the global "no false green" auditor for every LTD promotion.

### Add a Rafter check to every promotion

```text
Tier 4 -> Tier 3
Tier 3 -> Tier 2
Tier 2 -> Tier 1
```

### Required checks

```text
provider cannot publish directly
provider cannot own truth
off switch exists
empty key cannot pass as healthy
stub/fixture cannot pass as production
private data cannot leave allowed boundary
approval cannot be bypassed
receipt is fresh
```

### Acceptance test

```text
No LTD lane can be promoted to Tier 1 unless Rafter or an equivalent false-complete check passes.
```

---

## 14. Use ClickRank + Documentation.AI for Chummer's AI-search surface

ClickRank is already wired for `chummer.run` and `myexternalbrain.com` crawl and AI-search auditing. Documentation.AI is staged for AI-ready docs, cited assistant answers, `llms.txt`, semantic MDX, and private operator docs, while Git markdown/release receipts remain truth.

### Build this

```text
AI Search Trust Lane
├── Chummer public guide
├── registry release truth
├── docs projection via Documentation.AI
├── llms.txt
├── cited answer corpus
├── ClickRank crawl audit
└── stale answer detector
```

### First target questions

```text
Is Chummer6 available for Windows?
Is macOS supported?
How do I verify downloads?
How do I build from source?
What is Ready for Tonight?
How does Chummer6 differ from Chummer5a?
```

### Acceptance test

```text
External AI-search audit returns current platform and download truth, not stale Linux-only or gold-ready claims.
```

---

## 15. Use Internxt as cold archive, but not runtime truth

Internxt is still Tier 3 with no integration.

### Missed opportunity

100TB is too large to ignore. Use it for cold archive and disaster recovery drills, not active product truth.

### Candidate archives

```text
release artifacts
served artifact hash snapshots
proof receipts
Black Ledger source packets
media render candidates
public trust shelf packages
operator decision dossiers
```

### Required controls

```text
client-side encryption
restore drill
retention policy
access log
hash manifest
no active entitlement truth
no live user data truth
```

### Acceptance test

```text
Monthly archive drill restores one release artifact, one receipt bundle, and one public trust shelf packet, all hash-verified.
```

---

## 16. New top-level lane map

With the updated LTDs, I would reorganize the portfolio into this lane map:

| Lane                    | Primary LTDs                                                                                                       | Role                                                    |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------- |
| Background AI capacity  | `1min.AI`, staged `AI Magicx`, discovered `OMagic` later                                                           | Low-risk drafts, batch transforms, public-copy variants |
| Cross-repo discovery    | `vexp.dev`, BrowserAct                                                                                             | Semantic repo/LTD opportunity finding                   |
| Operator cockpit        | Teable                                                                                                             | OODA, proof debt, provider health, product signals        |
| Release trust           | Rafter, Pixefy, BrowserAct, ClickRank                                                                              | False-complete, visual QA, route proof, crawl proof     |
| Public docs/trust shelf | Documentation.AI, FlipLink, MarkupGo, ClickRank                                                                    | AI-ready docs, proof cards, guide presentation           |
| Feedback/roadmap        | ProductLift, MetaSurvey, Teable, ApproveThis                                                                       | Public signal to governed decision                      |
| Support concierge       | Answerly, Emailit, Rafter                                                                                          | Bounded support drafts and delivery                     |
| Black Ledger/media      | Subscribr, Syllabbles, Unmixr, MagicFit, VidBoard, JoggAI, Mootion, Nonverbia, PeekShot, FineTuning, Soundmadeseen | Scripts, narration, visuals, sound, QA                  |
| Onboarding/growth       | Deftform, Lunacal, Sendr, Signitic, Emailit                                                                        | Forms, booking, approved outreach, signatures           |
| Tours/runsite           | Crezlo, Pano2VR, AvoMap                                                                                            | Walkthroughs, maps, player-safe/GM-safe tours           |
| Billing tests           | PayFunnels, PayPal later                                                                                           | No-benefit billing test, future checkout proof          |
| Archive/DR              | Internxt                                                                                                           | Cold archive and restore drills                         |
| Strategy/research       | Vizologi, ICanpreneur, Headway, Paperguide                                                                         | Research and positioning packets                        |

---

## Highest-priority next actions

### P0: Convert the updated inventory into operational data

```text
[ ] Generate LTD_CAPABILITY_ROUTER.yaml from LTDs.md.
[ ] Generate LTD_PROOF_DEBT.generated.json.
[ ] Sync Tier 1-2 provider status into Teable.
[ ] Add Rafter false-complete checks to every Tier promotion.
[ ] Add vexp query pack for "where can each LTD help Chummer?"
```

### P1: Exploit new Tier 1 infrastructure

```text
[ ] Use 1min.AI for background low-risk queues.
[ ] Use Teable as the LTD/product OODA cockpit.
[ ] Use vexp.dev for cross-repo missed-opportunity discovery.
[ ] Use BrowserAct + Pixefy + Rafter + ClickRank as Release Trust Factory.
```

### P2: Promote high-value staged lanes

```text
[ ] Verify Subscribr API/export/channel map.
[ ] Verify MagicFit account-use receipts for remaining accounts.
[ ] Verify Documentation.AI site/llms.txt projection.
[ ] Verify MarkupGo render proof.
[ ] Verify OMagic account/capability inventory.
[ ] Verify YouBooks account capability and safe export semantics.
```

### P3: Build product-facing value loops

```text
[ ] Black Ledger production line.
[ ] AI-search public proof lane.
[ ] Support concierge.
[ ] No-desktop onboarding funnel.
[ ] Runsite walkthrough artifacts.
[ ] Audio campaign memory.
[ ] Creator publication operations dashboard.
```

---

## Bottom line

The updated `LTDs.md` changes the strategic answer.

Before, the opportunity was:

```text
Use LTDs as bounded external capability providers.
```

Now it is:

```text
Use LTDs as a governed operating system around Chummer6 and EA.
```

The new critical trio is:

```text
1min.AI = background capacity
Teable = live operations cockpit
vexp.dev = cross-repo opportunity index
```

Wrap those with:

```text
Rafter = false-complete/security gate
Pixefy = visual QA
BrowserAct = provider/route proof
ClickRank = crawl/AI-search proof
```

and the LTD portfolio becomes a compounding advantage rather than a collection of parked accounts.
