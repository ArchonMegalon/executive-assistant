# KARMA FORGE

## Table Pain

Every Shadowrun table has house rules, campaign-specific bans, local traditions, legacy custom data, and judgment calls. The pain is not that tables change rules. The pain is that changes become hidden folder magic, scattered Discord pins, private spreadsheets, incompatible forks, and surprise character legality problems.

Players need to know what changed before they join a table. GMs need to preview impact without becoming manual auditors. Communities need approved environments that travel across open runs. Creators need a way to publish reusable variants without turning Chummer into chaos.

## Bounded Product Move

KARMA FORGE is Chummer's governed house-rule and custom-rules layer. It turns a table rule into an explicit rule environment with packages, manifests, compatibility metadata, activation receipts, impact previews, approval posture, rollback, and restore behavior.

External tools may help discover demand, draft copy, interview GMs, schedule follow-up, and review candidate packs. They do not own rule authority. Rule truth stays inside engine packages, registry compatibility metadata, activation receipts, and explicit approval paths.

## Likely Owners

* `chummer6-core`
* `chummer6-hub`
* `chummer6-hub-registry`
* `chummer6-ui`
* `executive-assistant`

## Foundations

* `A1` - deterministic rules packages and catalog authority
* `A2` - ruleset ABI discipline and compatibility metadata
* `C0` - Hub-owned campaign and registry receipts
* `D2` - restore-safe sync, package portability, and missing-package warnings
* Product Governor approval paths for package promotion, public copy, and discovery outcomes
* External-tool boundaries from `EXTERNAL_TOOLS_PLANE.md`

## Why Still A Horizon

Rule changes can fracture tables quickly if compatibility, rollback, visibility, and restore behavior are not dependable first. KARMA FORGE should stay a horizon until a small vertical slice proves that a rule package can be activated, explained, tested against real runner dossiers, restored on another device, rolled back, and reviewed without violating engine authority.

The first proof should be campaign-scoped gear availability overlays. That slice proves package manifests, diffs, legality impact, player visibility, approval, restore, rollback, and reusable-packet shape without pretending the whole custom-rules universe is ready.

## Human Promise

**Change the table. Keep the trust.**

KARMA FORGE lets a campaign say:

> These are the rules we play with. This is what changed. This is why your runner is legal, blocked, or different. This is what happens if you join this campaign. This is what happens if the package changes later.

The player does not have to guess. The GM does not have to police everything manually. The creator does not have to ship fragile house-rule notes. The organizer does not have to maintain twelve conflicting pins.

Chummer shows the rule environment, the active packages, the impact, the compatibility, and the next safe action.

## What KARMA FORGE Does

KARMA FORGE turns house rules into explicit, inspectable objects.

A table can define or adopt:

* source packs
* rule presets
* amend packages
* campaign overlays
* availability changes
* chargen variants
* advancement variants
* optional subsystems
* world-linked rewards
* faction-linked unlocks
* scenario modifiers
* threat tags
* creator-published rule packs
* community-approved environments
* Chummer5a-style amend imports

Chummer should be able to answer:

* What packages are active?
* Who approved them?
* What changed?
* Which builds are affected?
* Which catalogs changed?
* Which entries were added, replaced, removed, or merged?
* Which operations were blocked?
* Which device is missing a package?
* Which runner was built under an older environment?
* Can this campaign still be restored on another install?
* Can this package be shared or published?

That is the difference between "we have a house rule" and "we have a governed rule environment."

## Rule Environment

A `RuleEnvironment` is the complete rules context for a runner, campaign, world, or community.

It can include:

```text
Base ruleset
Source packs
Rules presets
Amend packages
Option toggles
Campaign overlays
World offers
Threat tags
Scenario modifiers
Compatibility fingerprint
Activation receipts
Approval posture
```

A runner is not just "an SR6 character." A runner is an SR6 runner built under an exact campaign environment, with source packs, an amend graph, options, a fingerprint, and receipts.

When the environment changes, Chummer can show what changed before anyone plays under the wrong assumptions.

## Activation Receipts

Every meaningful rule change should create an `ActivationReceipt`.

The receipt tells the table:

* what package graph was requested
* what compiled successfully
* what changed in effective content
* what failed
* what was blocked
* what was missing
* what was downgraded
* what became lossy
* what compatibility fingerprint was used

Example:

```text
The GM activated Street-Level Gear Overlay.

Impact:
- three gear categories changed availability
- two items in this runner are now campaign-restricted
- one item remains legal because it was grandfathered by GM approval
- rollback path is available
```

The receipt is the safety rail. It gives the GM control and gives the player an explanation.

## GM View

A GM opens the campaign workspace and sees:

```text
Active Rule Environment:
Seattle Street-Level Season 01

Base:
SR6

Presets:
Street-Level Start
Restricted High-End Gear
Slow Advancement

Amend Packages:
Seattle Availability Overlay v1.2
Simplified Matrix Variant v0.8
Downtime Lifestyle Patch v1.0

Warnings:
2 runners have stale environment fingerprints.
1 player is missing Simplified Matrix Variant v0.8 locally.
3 builds changed legality since last review.
```

The GM can preview a rule change, see affected runners, publish a player-visible diff, require acknowledgement before the next session, roll back a package, promote a local rule to a reusable pack, share a campaign environment, and block play until incompatible builds are reviewed.

The GM gets control without becoming a manual rules auditor.

## Player View

A player joins an open run or campaign and sees:

```text
This table uses:
Seattle Street-Level Season 01

Different from base SR6:
- high-end cyberware availability is restricted
- Matrix rules use a simplified action model
- starting nuyen is reduced
- advancement pacing is slower
- two faction-linked reward packages may unlock later

Your runner:
- legal under base SR6
- blocked under this campaign until two gear choices are reviewed
- one alternative build path available
```

The player can show what changed, fix the build, ask the GM for approval, compare against base SR6, use a quickstart runner, or decline the campaign.

No silent rule drift. No surprise legality problem. No "I thought that was allowed."

## Living Communities

A community can define a `CommunityRuleEnvironment`.

Example:

```text
Community Hub Seattle Season 01

Allowed:
SR6 base
Street-Level preset
Community contacts package
Seattle district availability overlay

Banned:
selected high-end military gear
selected campaign-breaking edge cases

Required:
character review before open-run applications
active runner dossier
player acknowledgement of house rules
```

Every open run in that community can reference the same environment. Chummer can preflight whether a runner is legal, whether required packages are active, whether the player acknowledged table rules, and whether the runner matches the advancement band.

That turns community onboarding from a checklist of posts into a product flow.

## Creator Packs

Creators can publish rule packs as inspectable Chummer packages instead of PDF-only advice.

Creator packs should be:

* versioned
* checksummed
* described
* compatibility-labeled
* previewable
* testable
* reversible
* reviewable
* tied to example builds or campaigns
* able to show before and after impact

Examples:

* Street-Level Cyberware Economy
* Pink Mohawk Advancement
* Simplified Matrix for One-Shots
* High-Magic Campaign Overlay
* Faction Reward Pack: Renraku Black Channel
* BLACK LEDGER Season Unlocks
* Chummer5a Legacy Amend Pack Import

A GM can inspect the pack before adopting it. A player can see what it changes before joining. A community can approve it for a season.

That is the creator economy KARMA FORGE enables: reusable rule environments that do not destroy trust.

## BLACK LEDGER Link

BLACK LEDGER can feed KARMA FORGE through explicit world-linked packages.

Example:

```text
World Offer:
Renraku Black Channel Prototype Decks

Scope:
Seattle Season 01

Availability:
unlocked only after specific mission outcome

Effect:
selected restricted electronics become available through a campaign-specific channel

Visibility:
GM and eligible runners

Receipt:
linked to World Tick 007 and completed run result
```

Or:

```text
Threat Tag:
Tacoma Matrix Heat 4

Effect:
Renraku hosts in Tacoma gain stronger counter-intrusion posture.

Applies to:
mission packets in Tacoma this tick

Expires:
after heat drops below 3 or organizer resolves the pressure
```

BLACK LEDGER can create pressure and opportunity. KARMA FORGE makes the rule impact explicit. No invisible world-state mutation. No surprise rule changes. No faction manager secretly changing character legality.

## Supported Rule Categories

KARMA FORGE should start with the kinds of changes real tables actually ask for.

Character generation:

* alternate priority tables
* street-level starts
* higher-power starts
* restricted qualities
* banned options
* modified starting nuyen
* community-approved archetypes

Advancement:

* altered karma pacing
* nuyen pacing
* downtime training requirements
* milestone progression
* season caps
* catch-up mechanics for new players

Gear and availability:

* campaign-specific black markets
* restricted military gear
* faction-linked unlocks
* district-linked availability
* temporary scarcity
* grandfathered gear rules

Matrix:

* simplified action flow
* one-shot-friendly variants
* campaign-specific host assumptions
* alternate device and network handling

Magic:

* ritual constraints
* spirit limits
* drain variants
* mentor or spirit package changes
* blood-magic campaign overlays

Lifestyle and downtime:

* upkeep tuning
* contact maintenance
* downtime projects
* black clinic access
* safehouse rules

Opposition and NPCs:

* professional rating packages
* scaling rules
* threat tags
* faction asset templates
* run-specific scenario modifiers

Legacy migration:

* Chummer5a amend packs
* legacy custom data
* old campaign package behavior
* imports with explicit lossy or blocking receipts

## Discovery Pipeline

KARMA FORGE should not start by assuming the team knows every house rule users want. It should ask.

The discovery loop is:

```text
public prompt
structured pre-screen
adaptive interview
house-rule demand packet
EA clustering
Product Governor decision
KARMA FORGE candidate
prototype only after trust and scope are known
```

The goal is not to collect random feature requests. The goal is to learn what tables actually need Chummer to govern.

## House Rule Demand Packet

A user request becomes a structured `HouseRuleDemandPacket`.

Example:

```yaml
title: Campaign-scoped gear availability overlay
user_words: I want to mark gear unavailable until my campaign unlocks it.
interpreted_need: Campaign-scoped availability overlay with build-impact preview and player-visible receipts.
affected_domains:
  - gear
  - availability
  - character legality
  - campaign progression
likely_chummer_objects:
  - RuleEnvironment
  - AmendPackage
  - CampaignOverlayPackage
  - ActivationReceipt
trust_requirements:
  - player-visible before joining
  - build diff required
  - rollback required
  - approval required
  - restore-safe package fingerprint required
decision: Candidate for KARMA FORGE prototype
```

That is how Chummer turns messy human requests into safe product work.

## Chummer5a Continuity

KARMA FORGE should respect the power users already had.

Chummer5a custom data and amend files mattered because they let tables bend the tool around their campaign. Chummer6 should preserve the useful shapes while making them safer:

* full-file replacements where appropriate
* deterministic catalog merges
* selector-targeted add, replace, append, and remove operations
* legacy import where possible
* explicit lossy receipts where not possible
* manifest, priority, checksum, and compatibility validation

A legacy amend pack should become:

> This imported into the canonical amend graph. Here is what worked, what was lossy, and what requires review.

It should not stay as folder magic where the file exists and maybe changed something.

## Portability And Restore

A house rule is useful only if it follows the campaign safely.

KARMA FORGE must preserve:

* active rule-environment reference
* source pack references
* amend package references
* activation receipts
* compatibility fingerprint
* approval posture
* missing-package warnings
* restore behavior
* rollback path

Example:

```text
This runner expects:
Seattle Street-Level Season 01
Simplified Matrix Variant v0.8
Seattle Availability Overlay v1.2

This device has:
Seattle Street-Level Season 01
Seattle Availability Overlay v1.2

Missing:
Simplified Matrix Variant v0.8

Next safe action:
Download package, switch environment, or open in read-only mode.
```

No mystery drift. No wrong compute. No silent mismatch.

## Forge Experience

The KARMA FORGE experience should feel like a forge, not a settings panel.

A GM or creator should be able to:

1. choose what kind of rule they want to make
2. describe the intent
3. map the change to a safe package type
4. preview the impact
5. test against example runners
6. see compatibility warnings
7. generate an activation receipt
8. publish privately, to a campaign, to a community, or to the registry
9. revise with version history
10. retire or roll back when needed

The product should feel creative, but not lawless.

## Visibility And Consent

KARMA FORGE should always ask:

> Who needs to know before this rule affects play?

Every package needs visibility and approval posture:

```text
GM-only
player-visible
campaign-visible
community-approved
organizer-approved
public package
faction-secret
run-specific
temporary
retired
```

Some changes are GM-only scenario modifiers. Some are player-visible table rules. Some require explicit acknowledgement before joining a campaign. Some affect only rewards or availability. Some affect character legality. Some should be private until a run reveals them.

KARMA FORGE is not only about changing rules. It is about changing rules with the right people aware.

## Package Levels

Rule packages can live at different levels.

Personal sandbox:

* a GM experiments privately with a campaign idea

Campaign package:

* one table uses a rule environment for one campaign

Community environment:

* a living community approves a package set for a season

Creator pack:

* a creator publishes a reusable variant for other tables

World-linked offer:

* BLACK LEDGER unlocks a scoped package because of faction pressure or run outcomes

Each level needs different approval, visibility, and portability rules.

## Compatibility

A package should answer:

* Which ruleset does it target?
* Which source packs does it require?
* Which catalogs does it modify?
* Which packages conflict?
* Which packages are required first?
* Which versions are compatible?
* Which changes are safe?
* Which changes require review?
* Which runners are affected?
* Which campaigns already use it?

That lets communities avoid the worst failure mode: five house-rule packs are active and nobody knows why the build is wrong.

## Why GMs Care

GMs get visible and enforceable house rules, campaign environments, player-visible diffs, build-impact checks, safer onboarding, rollback, reusable presets, less manual review, easier open-run applications, world-linked rewards and threats, and legacy migration paths.

## Why Players Care

Players get no surprise house rules, clear build impact, before and after comparisons, active environment badges, missing-package warnings, restore safety, "why is this illegal?" explanations, campaign join preflight, and confidence that everyone is playing under the same environment.

## Why Creators Care

Creators get versioned rule packs, compatibility labels, preview receipts, example builds, community adoption paths, public trust, feedback loops, and update discipline.

## Why Organizers Care

Organizers get season-wide rule environments, open-run compatibility, approved package sets, player acknowledgement, GM adoption controls, rule-change history, and community migration safety.

## What KARMA FORGE Is Not

KARMA FORGE is not a second rules engine. Core still owns deterministic rules computation.

KARMA FORGE is not hidden custom-data magic. Every package needs a manifest, fingerprint, and receipt.

KARMA FORGE is not automatic AI house-rule creation. AI and external tools can help discover, draft, and review. Chummer-owned rule packages, reviews, and receipts determine what is real.

KARMA FORGE is not permission to silently mutate a campaign. Players and GMs need visibility, approval, and rollback.

KARMA FORGE is not a way to smuggle copyrighted book text into Chummer. Users should describe changes in their own words and use lawful references.

KARMA FORGE is not chaos. It is governed creativity.

## User Questions

Can I use KARMA FORGE for a private home campaign?

Yes. A GM can create a private campaign rule environment and use it only with their table.

Can a player see what changed?

Yes. Chummer should show before and after impact and explain why a runner is legal, blocked, or divergent.

Can I roll back a house rule?

Yes. Rule changes need receipts and rollback semantics so a campaign can recover safely.

Can I publish my house rules?

Eventually, yes. Published packages need compatibility metadata and approval paths.

Can I import Chummer5a custom data?

The goal is to preserve useful amend-pack power through safer legacy import. Some legacy behavior may import cleanly; some may produce lossy or blocking receipts.

Can BLACK LEDGER unlock rules or rewards?

Yes, through explicit world offers, threat tags, scenario modifiers, or campaign overlays. Nothing should mutate invisibly.

Can AI generate rules?

Not as authority. AI may help draft or discover demand. Chummer-owned rule packages, reviews, and receipts determine what is real.

Will this make every table incompatible?

Not if built correctly. KARMA FORGE exists specifically to prevent private-fork chaos by making rule environments explicit, compatible, and portable.

## First Version

The first useful KARMA FORGE slice should be campaign-scoped gear availability overlays.

It should let a GM:

1. create a campaign rule environment
2. add an availability overlay
3. preview affected gear
4. test against existing runner dossiers
5. show player-visible impact
6. activate with a receipt
7. restore on another device
8. roll back safely
9. share as a reusable candidate package

This proves package, diff, legality impact, player visibility, approval, restore, rollback, portability, and future publishing.

## Vision

Shadowrun tables are creative. They bend rules, patch friction, tune campaigns, build community traditions, invent strange rewards, scarier enemies, faster one-shots, slower campaigns, harsher streets, and weirder magic.

Chummer should not fight that.

Chummer should make it safe.

**KARMA FORGE is where house rules become real Chummer rules: visible, versioned, portable, explainable, and trusted.**

It is where a GM's table rule becomes a campaign environment. Where a community's tradition becomes an approved season pack. Where a creator's variant becomes something other tables can inspect and reuse. Where BLACK LEDGER's world consequences become playable rewards and threats. Where Chummer5a's custom-data legacy becomes a safer future.

KARMA FORGE is the place where tables shape their own Shadowrun without burning down the campaign.

## Canon Links

* `products/chummer/KARMA_FORGE_DISCOVERY_AND_HOUSE_RULE_INTAKE.md`
* `products/chummer/KARMA_FORGE_DISCOVERY_LAB_WORKFLOWS.yaml`
* `products/chummer/HOUSE_RULE_DISCOVERY_REGISTRY.yaml`
* `products/chummer/EXTERNAL_TOOLS_PLANE.md`
* `products/chummer/PREMIUM_AND_COMMUNITY_PACKAGING_MODEL.md`
