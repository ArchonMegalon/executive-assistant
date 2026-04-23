# Architecture

## Canonical rules

### Rule 1 — Central design wins

Cross-repo product truth lives in `chummer6-design`.
Code repos receive mirrored local context; they do not become the canonical source of cross-repo architecture.

### Rule 2 — Shared DTOs are package-owned

If a DTO crosses repo boundaries, it must have:

* a canonical package
* an owning repo
* a versioning policy
* a deprecation policy

No source-copy mirrors of cross-repo DTOs are allowed.

### Rule 3 — Engine semantics live in core

`chummer6-core` owns:

* rules math
* reducer truth
* runtime fingerprints
* runtime bundles
* explain provenance
* engine contract canon

No other repo may compute or redefine canonical mechanics.

### Rule 4 — Hosted orchestration lives in hub

`chummer6-hub` owns:

* identity
* relay
* approvals
* memory
* relationship-plane truth
* Coach / Spider / Director orchestration
* play API aggregation
* the initial bounded home for campaign continuity, product-control, and world-state domains
* account-aware download/install UX
* service-to-service coordination

It must not own duplicate mechanics, registry persistence after split, or media rendering after split.
If campaign continuity, product control, or world-state semantics live in Hub, they do so as explicit bounded contexts with dedicated contract families, not as a license for Hub to become the hidden owner of every middle-layer concern.

### Rule 5 — Workbench and play stay separate

`chummer6-ui` owns builder/workbench/admin/browser/desktop UX.
`chummer6-mobile` owns live-session/mobile/PWA/player/GM shell UX.

No silent re-merging of those surfaces is allowed.

### Rule 6 — UI-kit is the only shared UI boundary

Shared visual tokens, shell primitives, and reusable components belong in `chummer6-ui-kit`.
UI and mobile consume the package.
They do not fork it.

### Rule 7 — Registry is a service boundary

Artifact catalog, publication workflow, release channels, installs, update-feed metadata, reviews, and compatibility metadata belong in `chummer6-hub-registry`.

### Rule 8 — Media execution is a service boundary

Render jobs, manifests, previews, asset lifecycle, and provider adapters belong in `chummer6-media-factory`.

### Rule 9 — Legacy is reference-only

`chummer5a` is a migration/regression oracle. It is not part of the active multi-repo architecture.

### Rule 10 — Fleet is an execution plane, not product truth

`fleet` may orchestrate work, review, and landing across Chummer repos, but it does not become the canonical source of Chummer architecture.

Fleet may own:

* cheap-first automation policy
* worker account selection
* premium burst scheduling
* jury-gated landing control
* execution telemetry for repo work
* release matrix expansion and release-job orchestration
* publish/signoff history and compile-manifest evidence for release waves

Fleet must not own:

* product architecture truth
* product contract truth
* Hub user identity truth
* raw participant OpenAI auth state outside lane-local worker storage
* installer recipe truth
* canonical release-channel or update-feed truth

### Rule 11 — Petition upward, do not invent local truth

When a repo cannot finish work without widening a boundary, inventing a cross-repo contract, or contradicting mirrored canon, it must petition `chummer6-design`.

Blocked workers do not get to create silent local truth just because the blueprint is missing a seam.

### Rule 12 — Keep canon and operational evidence separate

Canonical design truth belongs in `products/chummer/*`.

Recurring parity/checksum/drift evidence belongs in automation-owned machine-readable outputs plus short human summaries.
The design repo must not become the main operational log sink for work that Fleet can verify automatically.

### Rule 13 — Community product semantics start in Hub, not Fleet

`fleet` may run sponsored premium lanes, but the reusable product plane for:

* user accounts
* groups and memberships
* join/boost codes
* fact/reward/entitlement ledgers
* leaderboards, badges, quests, and participation UX

belongs in `chummer6-hub`.

Boosting is the first use case of that platform, not a license to let Fleet absorb community-product ownership.

### Rule 14 — Participation canon starts in design, not in guide copy or helper scripts

The guided participation lane is a first-class product workflow.

Canonical workflow truth lives in `products/chummer/PARTICIPATION_AND_BOOSTER_WORKFLOW.md`, not in:

* `Chummer6` copy alone
* Fleet README prose alone
* EA helper scripts
* environment-variable folklore

Downstream helpers may render or explain that canon, but they must not become the source of it.

### Rule 15 — Package bootstrap must be deterministic

Package-first boundaries are not considered healthy unless restore/bootstrap is boring.

For `Chummer.Engine.Contracts` and `Chummer.Ui.Kit`, design canon must define:

* the canonical package ids
* the allowed local/CI feed posture
* the explicit compatibility-tree fallback for legacy consumers

Ambient monorepo-relative source references are not bootstrap truth.

### Rule 16 — Public landing and guide meaning start in design

`chummer.run` and `Chummer6` are downstream public surfaces with different jobs:

* `chummer.run` is the product front door, proof shelf, and invitation surface
* `Chummer6` is the deeper explainer and horizon guide

Canonical public-surface truth lives in design-owned files such as:

* `PUBLIC_LANDING_POLICY.md`
* `PUBLIC_LANDING_MANIFEST.yaml`
* `PUBLIC_FEATURE_REGISTRY.yaml`
* `PUBLIC_USER_MODEL.md`
* `PUBLIC_MEDIA_BRIEFS.yaml`
* `PUBLIC_VIDEO_BRIEFS.yaml`
* `MEDIA_ARTIFACT_RECIPE_REGISTRY.yaml`
* `PUBLIC_GUIDE_POLICY.md`

Hub may project that truth.
Guide generators may explain it.
Neither may invent a second public feature map.

### Rule 17 — Release control and update truth stay split

Release/build/install/update authority is intentionally split:

* `chummer6-core` owns runtime-bundle production and fingerprints
* `chummer6-ui` owns desktop packaging, installer recipes, and updater integration
* `fleet` owns release orchestration, matrix expansion, verify gates, and promotion evidence
* `chummer6-hub-registry` owns promoted channels, installer/update-feed metadata, compatibility, and runtime-bundle heads
* `chummer6-hub` renders public download/install UX by consuming registry truth
* `chummer6-media-factory` may render release visuals, but it does not own installers or publication/update policy

Neither EA helper scripts nor Hub-local release manifests may become the canonical build authority.

### Rule 18 — Campaign continuity is a first-class product domain

Chummer is not only a character builder and not only a repo graph.
It has a first-class product middle:

* runner dossier
* crew
* campaign
* run
* scene
* objective
* continuity snapshot
* replay-safe event memory

The initial cross-repo DTO family for that middle is `Chummer.Campaign.Contracts`.
It starts inside `chummer6-hub` as a bounded context until a later extraction is warranted.
UI, mobile, media, Fleet, and EA may project or consume campaign truth, but they must not redefine it.

### Rule 19 — Product control is a first-class plane

Crash, bug, feedback, release, and public-promise signals are not side effects.
They form a product-control plane with first-class truth for:

* support cases
* closure status
* decision packets
* release-readiness facts
* product-health and experience signals

The initial DTO family for that plane is `Chummer.Control.Contracts`.
It starts inside `chummer6-hub` as a bounded context that Hub owns for intake and closure, while Fleet consumes it for clustering and execution aids and design/governor roles consume it for governed change.

## Repo graph

```text
chummer6-design
  ├─ governs every Chummer repo
  └─ mirrors local guidance into code repos

chummer6-core
  ├─ publishes Chummer.Engine.Contracts
  ├─ computes mechanics truth
  └─ emits runtime bundle / explain / reducer semantics

chummer6-ui-kit
  └─ publishes Chummer.Ui.Kit

chummer6-ui
  ├─ consumes Chummer.Engine.Contracts
  ├─ consumes Chummer.Ui.Kit
  ├─ owns desktop packaging and updater integration
  └─ consumes hosted projections from hub / registry

chummer6-mobile
  ├─ consumes Chummer.Engine.Contracts
  ├─ consumes Chummer.Play.Contracts
  ├─ consumes Chummer.Ui.Kit
  └─ consumes hosted play projections from hub

chummer6-hub
  ├─ publishes Chummer.Play.Contracts
  ├─ publishes Chummer.Run.Contracts
  ├─ publishes Chummer.Campaign.Contracts
  ├─ publishes Chummer.Control.Contracts
  ├─ publishes Chummer.World.Contracts
  ├─ consumes Chummer.Engine.Contracts
  ├─ consumes Chummer.Hub.Registry.Contracts
  ├─ consumes Chummer.Media.Contracts
  └─ renders hosted workflows and registry-backed public download UX

chummer6-hub-registry
  ├─ publishes Chummer.Hub.Registry.Contracts
  └─ owns release/install/update/read-model truth

chummer6-media-factory
  └─ publishes Chummer.Media.Contracts

fleet
  ├─ consumes mirrored Chummer canon from chummer6-design
  ├─ owns parity automation and clustered queue synthesis for mirrored canon
  ├─ orchestrates repo work across Chummer codebases
  ├─ orchestrates release waves across core/ui/registry
  ├─ keeps cheap groundwork as the default execution plane
  └─ may open explicit premium burst lanes that still land through review authority
```

## Allowed dependency directions

### Allowed

* ui -> engine contracts
* ui -> ui-kit
* ui -> campaign contracts
* ui -> control contracts
* ui -> world contracts
* mobile -> engine contracts
* mobile -> play contracts
* mobile -> campaign contracts
* mobile -> world contracts
* mobile -> ui-kit
* hub -> engine contracts
* hub -> play contracts
* hub -> run contracts
* hub -> world contracts
* hub -> registry contracts
* hub -> media contracts
* media-factory -> campaign contracts
* media-factory -> world contracts
* hub-registry -> its own contracts
* media-factory -> its own contracts
* fleet -> mirrored design canon
* fleet -> code repos via git/worktree orchestration

### Forbidden

* core -> ui
* core -> mobile
* core -> hub
* mobile -> ui
* mobile -> hub implementation source
* ui -> mobile implementation source
* ui-kit -> domain DTO packages
* media-factory -> play contracts
* media-factory -> campaign/session DB semantics
* hub -> duplicated engine semantic DTOs once canonical package owner exists
* fleet -> canonical product design ownership
* hub -> raw participant Codex/OpenAI auth caches

## New repo split gate

A new repo split is not architecturally accepted until all of the following exist in `chummer6-design`:

* ownership row in `OWNERSHIP_MATRIX.md`
* active-repo entry in `products/chummer/README.md`
* implementation scope in `projects/*.md`
* mirror entry in `sync/sync-manifest.yaml`
* contract/package entry in `CONTRACT_SETS.yaml` if shared contracts are involved
* program milestone entries in `PROGRAM_MILESTONES.yaml`
* blocker update if the split introduces or resolves group risk
* review context coverage

## Drift conditions

A repo is considered architecturally drifting when any of the following is true:

* its README contradicts central design truth
* it owns a package it is not listed as owning
* its mirrored `.codex-design/*` is missing or stale
* it duplicates a contract family owned elsewhere
* it rebuilds a split boundary locally instead of consuming the package/service

## Petition and synthesis plane

Canonical split:

* `chummer6-design` owns petition resolution, blocker truth, milestone truth, and final boundary decisions
* `fleet` owns recurring mirror/parity verification plus clustering repeated drift findings into smaller, clearer queue work
* `executive-assistant` owns reasoning-heavy synthesis and petition-packet generation where LLM help is useful, plus provider-aware cognitive loops such as proactive horizon scans, human-edit reflection, bounded replanning, and interruption-budget throttling

The boring parity math should move downward into automation.
The upward path for real boundary questions should stay explicit and legal.

## Community sponsorship plane

Canonical split:

* `chummer6-hub` owns the community/accounting plane
* `fleet` owns the sponsored worker plane
* `executive-assistant` owns provider-aware telemetry and runtime substrate

Implementation order:

1. Hub user accounts and profiles
2. Hub generic groups and memberships
3. Hub fact/reward/entitlement ledgers
4. Hub participation UX
5. Fleet dynamic participant lanes and receipt emission
6. Hub leaderboards, quests, badges, and entitlement-backed perks

Do not invert that order by making Fleet the first home of boost-code product behavior.

The detailed workflow, rollout posture, recognition rules, and bootstrap truth live in `PARTICIPATION_AND_BOOSTER_WORKFLOW.md`.


## External tools plane

Project Chummer has an explicit External Tools Plane.

This plane exists to integrate owned third-party capabilities without allowing any third-party capability to become canonical Chummer truth.

### External tools plane rules

1. External tools always sit behind Chummer-owned adapters.
2. External tools may assist, project, notify, visualize, render, or archive.
3. External tools may not own:

   * rules truth
   * reducer truth
   * runtime truth
   * session truth
   * approval truth
   * registry truth
   * artifact truth
   * memory/canon truth
4. No client repo may access third-party tools directly.
5. All external-provider-assisted outputs that re-enter Chummer must carry Chummer-side provenance and receipts.
6. `chummer6-hub` owns orchestration-side integrations.
7. `chummer6-media-factory` owns render/archive integrations.
8. `chummer6-design` owns external-tools policy and rollout governance.

### External tools plane by repo

* `chummer6-hub`

  * reasoning providers
  * approval bridges
  * docs/help bridges
  * survey bridges
  * automation bridges
  * research/eval tooling
  * participation consent and sponsorship UX for Fleet burst lanes

* `chummer6-media-factory`

  * document render adapters
  * preview/thumbnail adapters
  * image/video adapters
  * route visualization adapters
  * cold-archive adapters

* `chummer6-hub-registry`

  * references to promoted reusable template/style/help/preview artifacts only

### Non-goals

* no third-party tool is a required hop for live session relay
* no third-party tool holds canonical approval state
* no third-party tool owns Chummer media manifests
* no third-party tool bypasses Chummer moderation or canonization
* no hosted UX stores raw participant Codex/OpenAI auth caches; those stay lane-local on the execution host

## Community sponsorship plane

Chummer uses one community/sponsorship spine rather than a one-off contribution-only feature.

Canonical split:

* `chummer6-hub` = account, community, group, ledger, sponsorship, and entitlement plane
* `fleet` = sponsored worker and landing-control plane
* `executive-assistant` = provider-aware substrate and ownership telemetry plane

### Canonical concepts

* identity principal: authenticated subject/session issued by Hub identity
* user account: product-level human account linked to one or more principals
* group: reusable social/authority container with `group_type`, `visibility`, `capabilities`, and policy
* membership: a user’s role relation to a group
* sponsor session: a bounded premium-burst sponsorship intent/execution record
* entitlement: a durable product right granted to a user or group

User accounts must not collapse into raw identity-subject rows. Groups must stay generic enough to serve guided-contribution groups now and campaign / GM-circle / creator-team surfaces later.

### Accounting rule

Chummer keeps three distinct journals:

1. fact ledger: immutable raw events and contribution receipts
2. reward journal: derived score, badge, streak, quest, and leaderboard accounting
3. entitlement journal: durable product-right grants and revocations

These journals must not be merged into one implicit score table.

### Booster participation rule

Boosting is modeled as:

1. account or group joins a campaign / redeems a code / creates a sponsor session intent
2. consent is recorded in Hub
3. Fleet opens the participant lane and performs device auth on the execution host
4. Fleet emits signed contribution receipts after meaningful work events
5. Hub ingests receipts into the fact ledger
6. reward and entitlement rules derive downstream projections from those receipts

Points and perks must not be granted merely for linking an account or creating an idle lane.
