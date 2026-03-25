# Ownership matrix

## Summary table

| Repo                    | Primary mission                    | Owns                                                                                                    | Must not own                                                                       | Key package(s)                                                                  |
| ----------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `chummer6-design`        | central design governance          | canon, ownership, milestones, blockers, sync, review guidance                                           | code implementation, hidden parallel product docs                                  | none                                                                            |
| `chummer6-core`   | deterministic rules/runtime engine | engine truth, reducer truth, runtime bundles, runtime fingerprints, explain canon, engine contracts     | play UI, workbench UI, registry persistence, media execution, hosted orchestration | `Chummer.Engine.Contracts`                                                      |
| `chummer6-ui`  | workbench/browser/desktop UX       | builders, inspectors, compare, explain UX, admin/moderation UX, desktop packaging, installer/updater recipes, Windows `.exe` / macOS `.dmg` / Linux `.deb` release targets, desktop-head startup-smoke fixtures, updater client behavior, local install state, staged apply helpers, installation identity material, in-app feedback/bug/crash entry points, local crash interception, diagnostics bundles, recovery dialogs, redacted crash-envelope forwarding to Hub-owned intake | play shell, rule evaluation, offline ledger, media execution, registry rollout truth, canonical channel/update-feed truth, hosted support ticket truth, direct Fleet crash intake, per-user installer generation | consumes `Chummer.Engine.Contracts`, `Chummer.Ui.Kit`                           |
| `chummer6-mobile`          | live session/mobile/PWA shell      | player shell, GM shell, offline ledger, sync client, play-safe Coach/Spider surfaces                    | builder UX, rule evaluation, registry/moderation, provider secrets                 | consumes `Chummer.Engine.Contracts`, `Chummer.Play.Contracts`, `Chummer.Ui.Kit` |
| `chummer6-hub`  | relationship/orchestration plus campaign/control plane | identity, user accounts, groups, memberships, ledgers, participation UX, relay, approvals, memory, Coach/Spider/Director orchestration, delivery, play API aggregation, campaign spine truth, runner dossier continuity, crew/campaign/run/scene/objective semantics, registry-backed downloads UX, download-receipt and install-claim flows, claimed-install account linkage, account-aware install guidance, support intake, crash-intake normalization, ticket threads, decision packets, knowledge/help surfaces, surveys, human escalation, later support-assistant handoff, normalized crash work-item emission | duplicate mechanics, registry persistence after split, media rendering after split, raw participant auth caches, Fleet worker execution, release manifest generation truth, update-feed truth, client-side crash interception, personalized installer binaries | `Chummer.Play.Contracts`, `Chummer.Run.Contracts`, `Chummer.Campaign.Contracts`, `Chummer.Control.Contracts`, consumes `Chummer.Hub.Registry.Contracts` |
| `chummer6-ui-kit`        | shared design system               | tokens, themes, shell primitives, accessibility primitives, reusable components                         | domain DTOs, HTTP clients, storage, rules math                                     | `Chummer.Ui.Kit`                                                                |
| `chummer6-hub-registry`  | catalog/publication service        | artifacts, publication drafts, release channels, desktop release heads, installs, update feeds, rollout/revocation state, reviews, compatibility, runtime-bundle heads, crash-triage enrichment facts derived from release/install/update truth | relay, Coach/Spider, media rendering, client UX, installer build execution, support ticket/help truth | `Chummer.Hub.Registry.Contracts`                                                |
| `chummer6-media-factory` | media execution plant              | render jobs, previews, manifests, asset lifecycle, provider adapters, signed asset access               | campaign truth, rules truth, approvals policy, player/client UX                    | `Chummer.Media.Contracts`                                                       |
| `fleet`                  | execution/control plane            | worker orchestration, queue policy, review/landing control, cheap-first automation, explicit premium burst lanes, lane-local auth helpers, sponsor-session receipts, release orchestration, cross-platform build/start smoke execution, signing/notarization jobs, publish/signoff evidence, normalized crash clustering/repro/test/patch-prep automation, release-regression OODA packets for startup smoke failures | product truth, contract canon, session truth, user/group/ledger truth, raw hosted identity/auth storage, installer recipe truth, canonical release-channel truth, canonical crash/support truth      | none                                                                            |
| `executive-assistant`    | governed synthesis/runtime substrate | provider-aware runtime substrate, petition-packet and design-synthesis helpers, proactive horizon scans, human-edit reflection, bounded replanning, interruption-budget throttling, mirror-status briefs, ownership telemetry derived from mirrored canon | canonical product truth, queue/milestone/blocker truth, support-case truth, release-channel or update-feed truth, hidden guide/help canon, direct landing authority | none                                                                            |
| `chummer5a`             | legacy oracle                      | migration fixtures, regression corpus, legacy compatibility reference                                   | vNext architecture ownership                                                       | none                                                                            |

## Program-level stewardship roles

### Lead designer

Owns:

* canonical product truth
* repo and package boundaries
* milestone and blocker canon
* public-story and horizon canon

Must not own:

* raw support inbox
* worker execution
* day-to-day stop/replan authority just because a live issue exists

### Product governor

Owns:

* whole-product health
* support and feedback closure posture
* cross-repo scope pressure review
* stop, freeze, reroute, and escalation authority when reality diverges from current plan
* the weekly pulse defined in `PRODUCT_HEALTH_SCORECARD.yaml`

Must not own:

* raw support-case truth
* package canon
* repo-local implementation detail
* direct worker execution

## Boundary notes

### `chummer6-core`

The only repo allowed to define canonical mechanics truth.

### `chummer6-ui`

The only repo allowed to define workbench/browser/desktop product UX.
It is also the only repo allowed to own desktop updater client behavior, local update state, staged apply helpers, installation-local credentials, local crash interception, diagnostics bundle creation, and next-launch recovery UX.
It must not redefine published channel or update-feed truth or hosted support-case truth.

### `chummer6-mobile`

The only repo allowed to define the dedicated live play/mobile shell.

### `chummer6-hub`

The only repo allowed to own the reusable community/accounting plane and hosted orchestration, but not the only repo allowed to own hosted services.
Registry and media must remain separate service boundaries.
Hub may explain install and update posture, and it owns support-case/help truth, but it does not become the feed authority and it does not reclaim client-side crash interception.
Hub owns the person/install relationship, install claim tickets, installation grants, and support-status closure, but it does not mutate signed release artifacts into per-user binaries.
Hub is also the owned intake/orchestration seam for crash automation; Fleet consumes normalized work from Hub rather than raw client crash submissions.
Hub owns raw support and feedback intake plus user-facing closure, but it does not become the product governor.
Hub is the initial bounded home of the campaign spine and product-control plane, but that does not make it the hidden owner of every middle-layer concern in perpetuity.

### `chummer6-ui-kit`

The only repo allowed to own shared cross-head UI primitives.

### `chummer6-hub-registry`

The only repo allowed to own immutable artifact catalog, publication/install/update truth, promoted release channels, and desktop release heads.
Support surfaces may read that truth, but Registry does not become a help-desk or ticket system.
Crash automation may enrich incidents from Registry facts, but that does not move intake or case truth into Registry.

### `chummer6-media-factory`

The only repo allowed to own render execution and render-asset lifecycle.

### `fleet`

The only adjacent repo allowed to own cross-repo worker scheduling, release orchestration, participant worker lifecycle, and landing control, but never canonical Chummer product truth.
Fleet may automate crash clustering, repro, test drafting, and candidate patch preparation only after Hub-owned normalization and Registry-backed release enrichment.
Fleet may prepare evidence packets and queue proposals for designer or product-governor review, but it does not own whole-product stop/replan authority.

### `executive-assistant`

The only adjacent repo allowed to own the provider-aware runtime substrate for governed assistant execution, petition-packet generation, design-synthesis helpers, proactive horizon scans, human-edit reflection, bounded replanning, interruption-budget throttling, and mirror-status briefs.
It may project telemetry and bounded operator aids downstream of mirrored canon, but it must not become a second source of product, queue, support, release, or guide truth.

## Ownership violations

Any of the following is an ownership violation:

* a repo introduces a shared cross-repo DTO family outside its canonical package
* hub reintroduces media rendering or registry persistence after those splits complete
* ui reclaims play-shell ownership
* ui invents a second promoted channel vocabulary or local feed truth
* desktop clients send raw crash payloads straight to Fleet as the primary seam
* Fleet hot-patches production or lands code from a single crash report without the normal review/release path
* a chat assistant becomes the required first support lane or the gate in front of crash/bug reporting
* a vendor help desk or AppSumo tool becomes the canonical crash or ticket system
* Hub or UI personalizes desktop installers per user instead of using claimable installs
* mobile reimplements rules truth
* ui-kit gains domain DTOs or HTTP clients
* engine begins depending on ui/mobile/hub code
* design repo becomes stale enough that code repos must invent architecture locally
* fleet introduces execution policy that contradicts mirrored design canon
* hub or fleet become the runtime update authority for desktop clients


## External integration ownership

### `chummer6-design`

Owns:

* external-tool classification
* approved usage policy
* system-of-record rules
* rollout governance
* provenance requirements

Must not own:

* provider SDK implementations
* runtime secrets
* vendor adapters

### `chummer6-hub`

Owns:

* orchestration-side external integrations
* reasoning-provider routing
* approval bridges
* docs/help bridges
* support/help-desk bridges
* survey bridges
* automation bridges
* research/eval/prompt-tooling integrations
* later grounded support-assistant or human-handoff layers

Must not own:

* media rendering internals
* client-side vendor access
* duplicate engine semantics
* raw participant Codex/OpenAI auth caches

### `chummer6-media-factory`

Owns:

* render/archive adapters
* provider-run receipts for media work
* media provenance capture
* media archive execution

Must not own:

* approvals policy
* campaign/session meaning
* client UX
* registry truth

### `chummer6-ui` and `chummer6-mobile`

Must not own:

* vendor credentials
* direct provider SDK access
* direct third-party orchestration

### `fleet`

Owns:

* cheap-first execution policy
* jury-gated landing automation
* dynamic participant burst lanes after explicit Hub consent
* lane-local auth/cache storage on the execution host
* sponsor-session execution metadata on participant lanes
* signed contribution receipts emitted from meaningful execution events

Must not own:

* product architecture canon
* raw desktop crash/client support intake
* direct Hub identity/session issuance
* participant-consent UX outside the Hub boundary
* canonical user, group, reward, or entitlement ledger truth
* boost-code-first product logic that should live in Hub

Fleet must also keep guide-generation and guide-verification truth downstream of `chummer6-design` instead of hiding canonical participation semantics behind EA-side helper code.

### `executive-assistant`

Owns:

* provider-aware runtime substrate for governed assistant execution
* petition and synthesis packet generation downstream of mirrored canon
* proactive horizon scans, human-edit reflection, bounded replanning, and interruption-budget throttling
* mirror-status briefs and ownership telemetry derived from design-owned truth

Must not own:

* canonical product, queue, milestone, blocker, or contract truth
* raw support-case, account, group, reward, or entitlement truth
* release-channel, install, or update-feed truth
* hidden guide/help canon that other repos must reverse-engineer
* direct merge, landing, or freeze authority

### `chummer6-hub`

Owns:

* identity principal to product-user mapping
* user accounts and profiles
* generic groups, memberships, join codes, and boost codes
* download receipts, install claim tickets, claimed-install grants, and account-linked support closure
* fact ledger, reward journal, and entitlement journal
* sponsor-session UX, community visibility, badges, quests, and leaderboards

Must not own:

* raw participant Codex/OpenAI auth caches
* Fleet worker-process lifecycle or repo landing control
* provider-secret ownership or provider-runtime accounting

### Participation workflow note

The canonical sponsor/consent/device-auth/lane/receipt/revoke workflow is defined centrally in `products/chummer/PARTICIPATION_AND_BOOSTER_WORKFLOW.md`.
Hub, Fleet, EA, and `Chummer6` must compile from that workflow instead of carrying parallel product interpretations.
