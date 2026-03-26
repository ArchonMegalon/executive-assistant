# Project Chummer

Project Chummer is a multi-repo modernization of the legacy Chummer 5 application into a deterministic engine, workbench experience, campaign and living-dossier spine, play/mobile session shell, hosted relationship/orchestration plane, shared design system, artifact registry, and dedicated media execution service.

## Product entry

Start with `START_HERE.md` if you are new.
Use `GLOSSARY.md` when the repo-specific language gets dense.
Use `journeys/README.md` when the question is "what does the user actually do end to end?"
Use `METRICS_AND_SLOS.yaml` when the question is "what counts as good enough to ship?"
Use `PRODUCT_HEALTH_SCORECARD.yaml` when the question is "how does whole-product reality steer the next decision?"

### Reading tracks

1. Public/product story:
   `VISION.md` -> `PUBLIC_LANDING_POLICY.md` -> `PUBLIC_NAVIGATION.yaml` -> `PUBLIC_LANDING_MANIFEST.yaml` -> `PUBLIC_FEATURE_REGISTRY.yaml` -> `PUBLIC_PROGRESS_PARTS.yaml` -> `PUBLIC_CAMPAIGN_IMAGE_MANIFEST.yaml` -> `PUBLIC_USER_MODEL.md` -> `PUBLIC_AUTH_FLOW.md`
2. Product middle and control loop:
   `CAMPAIGN_SPINE_AND_CREW_MODEL.md` -> `CHARACTER_LIFECYCLE_AND_LIVING_DOSSIER.md` -> `ROAMING_WORKSPACE_AND_ENTITLEMENT_SYNC.md` -> `CAMPAIGN_WORKSPACE_AND_DEVICE_ROLES.md` -> `INTEROP_AND_PORTABILITY_MODEL.md` -> `USER_JOURNEYS.md` -> `PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md` -> `SUPPORT_AND_SIGNAL_OODA_LOOP.md` -> `EXPERIENCE_SUCCESS_METRICS.md`
3. Repo and contract boundaries:
   `ARCHITECTURE.md` -> `OWNERSHIP_MATRIX.md` -> `LEAD_DESIGNER_OPERATING_MODEL.md` -> `PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md` -> `CONTRACT_SETS.yaml` -> `projects/*.md`
4. Delivery and release control:
   `RELEASE_PIPELINE.md` -> `PUBLIC_RELEASE_EXPERIENCE.yaml` -> `PUBLIC_DOWNLOADS_POLICY.md` -> `DESKTOP_AUTO_UPDATE_SYSTEM.md` -> `PUBLIC_AUTO_UPDATE_POLICY.md` -> `FEEDBACK_AND_CRASH_REPORTING_SYSTEM.md` -> `FEEDBACK_AND_SIGNAL_OODA_LOOP.md` -> `FEEDBACK_AND_CRASH_STATUS_MODEL.md` -> `ACCOUNT_AWARE_FRONT_DOOR_CLOSEOUT.md` -> `PROGRAM_MILESTONES.yaml` -> `GROUP_BLOCKERS.md` -> `RELEASE_EVIDENCE_PACK.md`
5. Future lanes and public explainer posture:
   `HORIZONS.md` -> `HORIZON_REGISTRY.yaml` -> `BUILD_LAB_PRODUCT_MODEL.md` -> `PUBLIC_GUIDE_POLICY.md` -> `PUBLIC_GUIDE_PAGE_REGISTRY.yaml` -> `PUBLIC_PART_REGISTRY.yaml` -> `PUBLIC_FAQ_REGISTRY.yaml` -> `NEXT_WAVE_ACCOUNT_AWARE_FRONT_DOOR.md` -> `NEXT_20_BIG_WINS_EXECUTION_PLAN.md` -> `NEXT_20_BIG_WINS_REGISTRY.yaml` -> `POST_AUDIT_NEXT_20_BIG_WINS_CLOSEOUT.md` -> `POST_AUDIT_NEXT_20_BIG_WINS_GUIDE.md` -> `POST_AUDIT_NEXT_20_BIG_WINS_REGISTRY.yaml`

### Full canonical set

1. `START_HERE.md`
2. `GLOSSARY.md`
3. `VISION.md`
4. `HORIZONS.md`
5. `HORIZON_REGISTRY.yaml`
6. `ARCHITECTURE.md`
7. `LEAD_DESIGNER_OPERATING_MODEL.md`
8. `PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md`
9. `PRODUCT_HEALTH_SCORECARD.yaml`
10. `RELEASE_PIPELINE.md`
11. `PUBLIC_DOWNLOADS_POLICY.md`
12. `DESKTOP_AUTO_UPDATE_SYSTEM.md`
13. `PUBLIC_AUTO_UPDATE_POLICY.md`
14. `ACCOUNT_AWARE_INSTALL_AND_SUPPORT_LINKING.md`
15. `FEEDBACK_AND_CRASH_REPORTING_SYSTEM.md`
16. `FEEDBACK_AND_SIGNAL_OODA_LOOP.md`
17. `FEEDBACK_AND_CRASH_AUTOMATION.md`
18. `FEEDBACK_AND_CRASH_STATUS_MODEL.md`
19. `PUBLIC_LANDING_POLICY.md`
20. `PUBLIC_LANDING_MANIFEST.yaml`
21. `PUBLIC_FEATURE_REGISTRY.yaml`
22. `PUBLIC_LANDING_ASSET_REGISTRY.yaml`
23. `PUBLIC_USER_MODEL.md`
24. `PUBLIC_AUTH_FLOW.md`
25. `IDENTITY_AND_CHANNEL_LINKING_MODEL.md`
26. `PUBLIC_MEDIA_BRIEFS.yaml`
27. `PARTICIPATION_AND_BOOSTER_WORKFLOW.md`
28. `COMMUNITY_SPONSORSHIP_BACKLOG.md`
29. `EXTERNAL_TOOLS_PLANE.md`
30. `LTD_CAPABILITY_MAP.md`
31. `PUBLIC_GUIDE_POLICY.md`
32. `PUBLIC_GUIDE_PAGE_REGISTRY.yaml`
33. `PUBLIC_PART_REGISTRY.yaml`
34. `PUBLIC_FAQ_REGISTRY.yaml`
35. `PUBLIC_HELP_COPY.md`
36. `PUBLIC_GUIDE_EXPORT_MANIFEST.yaml`
37. `HORIZON_SIGNAL_POLICY.md`
38. `PUBLIC_MEDIA_AND_GUIDE_ASSET_POLICY.md`
39. `METRICS_AND_SLOS.yaml`
40. `PUBLIC_TRUST_CONTENT.yaml`
41. `journeys/README.md`
42. `OWNERSHIP_MATRIX.md`
43. `PROGRAM_MILESTONES.yaml`
44. `CONTRACT_SETS.yaml`
45. `GROUP_BLOCKERS.md`
46. `projects/*.md` for repo-specific scope
47. `CAMPAIGN_SPINE_AND_CREW_MODEL.md`
48. `CHARACTER_LIFECYCLE_AND_LIVING_DOSSIER.md`
49. `ROAMING_WORKSPACE_AND_ENTITLEMENT_SYNC.md`
50. `CAMPAIGN_WORKSPACE_AND_DEVICE_ROLES.md`
51. `PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md`
52. `SUPPORT_AND_SIGNAL_OODA_LOOP.md`
53. `USER_JOURNEYS.md`
54. `EXPERIENCE_SUCCESS_METRICS.md`
55. `PUBLIC_NAVIGATION.yaml`
56. `PUBLIC_PROGRESS_PARTS.yaml`
57. `PUBLIC_CAMPAIGN_IMAGE_MANIFEST.yaml`
58. `PUBLIC_RELEASE_EXPERIENCE.yaml`
59. `BUILD_LAB_PRODUCT_MODEL.md`
60. `ACCOUNT_AWARE_FRONT_DOOR_CLOSEOUT.md`
61. `NEXT_WAVE_ACCOUNT_AWARE_FRONT_DOOR.md`
62. `NEXT_15_BIG_WINS_EXECUTION_PLAN.md`
63. `NEXT_20_BIG_WINS_EXECUTION_PLAN.md`
64. `NEXT_20_BIG_WINS_REGISTRY.yaml`
65. `POST_AUDIT_NEXT_20_BIG_WINS_CLOSEOUT.md`
66. `POST_AUDIT_NEXT_20_BIG_WINS_GUIDE.md`
67. `POST_AUDIT_NEXT_20_BIG_WINS_REGISTRY.yaml`
68. `INTEROP_AND_PORTABILITY_MODEL.md`

`HORIZON_REGISTRY.yaml` is the machine-readable source for horizon existence, order, public-guide eligibility, and eventual build path.
The current horizon set covers knowledge fabric, spatial/runsite artifacts, creator press, replay/forensics, and bounded table coaching in addition to the earlier continuity and simulation lanes.
`CAMPAIGN_SPINE_AND_CREW_MODEL.md` is the missing-middle canon for the campaign-scale product: runner dossier, crew, campaign, run, scene, objective, continuity, and replay-safe event memory.
`CHARACTER_LIFECYCLE_AND_LIVING_DOSSIER.md` is the canonical bridge from deterministic build truth into the long-lived dossier a player, GM, campaign, and artifact lane actually carry forward.
`ROAMING_WORKSPACE_AND_ENTITLEMENT_SYNC.md` defines how claimed installs restore person, campaign, and entitlement-shaped workspace truth across devices without mutating signed artifacts, syncing secrets, or hiding conflict semantics.
`CAMPAIGN_WORKSPACE_AND_DEVICE_ROLES.md` defines the next visible product layer on top of roaming workspace: the home cockpit, campaign workspace, what-changed-for-me packet, and install-local device roles such as workstation, play tablet, observer screen, travel cache, and preview scout.
`INTEROP_AND_PORTABILITY_MODEL.md` makes import/export, portable dossier and campaign packages, migration receipts, and round-trip provenance first-class product promises instead of leaving them as compatibility folklore.
`PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md` defines the product-control plane as a first-class middle layer instead of leaving whole-product steering implicit in support notes or operator habit.
`SUPPORT_AND_SIGNAL_OODA_LOOP.md` defines how support, crash, feedback, release, and public-promise signals become governed packets that can actually change design, docs, queue, or release posture.
`USER_JOURNEYS.md` is the top-level product map for Build, Explain, Run, Publish, and Improve, with the detailed happy-path/failure-mode canon still living under `journeys/*.md`.
`EXPERIENCE_SUCCESS_METRICS.md` translates repo and release gates back into user-facing promises so the product is measured as a lived system, not only as a clean repo graph.
`RELEASE_PIPELINE.md` is the canonical source for where release orchestration, desktop packaging, runtime-bundle production, registry publication truth, updater feeds, and public download/install rendering belong.
`PUBLIC_DOWNLOADS_POLICY.md` and `PUBLIC_AUTO_UPDATE_POLICY.md` are the public copy and CTA truth for `/downloads` and in-app update promises, so landing/help/guide surfaces cannot drift away from the install/update contract.
`DESKTOP_AUTO_UPDATE_SYSTEM.md` is the canonical source for the first desktop self-update wave, including the split between install media, machine update payloads, registry-owned release heads, rollout states, and UI-owned apply helpers.
`FEEDBACK_AND_CRASH_REPORTING_SYSTEM.md` is the canonical source for the first support plane, including the split between crash reporting, structured bug reporting, lightweight feedback, Hub-owned case truth, and the rule that the grounded support assistant stays an optional phase-2 layer rather than the gate in front of real support intake.
`FEEDBACK_AND_SIGNAL_OODA_LOOP.md` is the canonical routing loop from raw support, survey, public-issue, and release signals into code, docs, queue, policy, or canon action.
`ACCOUNT_AWARE_INSTALL_AND_SUPPORT_LINKING.md` is the canonical source for Hub-first downloads, claimable installs, installation-level auth, and the rule that Chummer personalizes the relationship rather than the binary.
`FEEDBACK_AND_CRASH_STATUS_MODEL.md` is the canonical source for support-case status events, fix-available notices, and post-release follow-up rules.
`PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md` defines the whole-product operator seam between reality and canon, while `PRODUCT_HEALTH_SCORECARD.yaml` defines the weekly pulse that role uses to freeze, reroute, or escalate work.
`WEEKLY_PRODUCT_PULSE.generated.json` is the generated weekly snapshot that turns the scorecard and progress history into a bounded governor-ready decision artifact.
`PUBLIC_LANDING_MANIFEST.yaml`, `PUBLIC_FEATURE_REGISTRY.yaml`, and `PUBLIC_LANDING_ASSET_REGISTRY.yaml` are the machine-readable source for the `chummer.run` landing structure, CTA routing, public proof shelf, asset slots, and signed-in overlay posture.
`PUBLIC_NAVIGATION.yaml` and `PUBLIC_PROGRESS_PARTS.yaml` define the public front-door routes and the public pulse grouping, while `PUBLIC_CAMPAIGN_IMAGE_MANIFEST.yaml` is the canonical campaign-art direction for the front door rather than an orphan media sidecar.
`PUBLIC_PROGRESS_PARTS.yaml` is the canonical product-part mapping, public copy registry, and ETA/momentum policy input for the hosted `/progress` report, while `PROGRESS_REPORT.generated.json`, `PROGRESS_REPORT.generated.html`, and `PROGRESS_REPORT_POSTER.svg` are generated downstream projections that Hub may serve directly. The raster-only rule in the public media briefs applies to front-door campaign art rather than these generated progress exports.
`PUBLIC_RELEASE_EXPERIENCE.yaml` is the canonical guest and signed-in release shelf posture for `/downloads`, install help, known-issue routing, and the trust language around promoted versus preview desktop heads.
`PUBLIC_AUTH_FLOW.md` defines the first-wave login/signup/logout posture, guest fallbacks, and which provider surfaces may appear publicly in the hosted shell.
`IDENTITY_AND_CHANNEL_LINKING_MODEL.md` is the canonical source for email hygiene, social bootstrap, linked identities, official companion channels, and the rule that EA stays the orchestrator brain behind those channels.
`PUBLIC_GUIDE_PAGE_REGISTRY.yaml`, `PUBLIC_PART_REGISTRY.yaml`, `PUBLIC_FAQ_REGISTRY.yaml`, and `PUBLIC_HELP_COPY.md` are the machine-readable and public-safe source of truth for downstream guide generation outside the landing surface, including the generated download/build shelf.
`METRICS_AND_SLOS.yaml` is the release-scorecard canon for measurable user-trust, continuity, publication, and install/update gates.
`PUBLIC_TRUST_CONTENT.yaml` is the canonical trust-content manifest for help, contact, and support statements surfaced at `/help`, `/contact`, and `/downloads`.
`journeys/*.md` defines the top end-to-end user flows and failure-mode recoveries that multiple repos must preserve.
`BUILD_LAB_PRODUCT_MODEL.md` defines Build Lab as a flagship Build plus Explain surface rather than leaving it as a downstream milestone label without a canonical product promise.
`ACCOUNT_AWARE_FRONT_DOOR_CLOSEOUT.md` records the just-closed install, update, support, and operator-control wave so roadmap and milestone language does not lag the public-main implementation.
`POST_AUDIT_NEXT_20_BIG_WINS_CLOSEOUT.md` records the post-audit closeout boundary and keeps `ROADMAP.md`, public proof evidence, and registry status aligned.
`NEXT_WAVE_ACCOUNT_AWARE_FRONT_DOOR.md` remains the historical milestone spine for the front-door wave, while `NEXT_15_BIG_WINS_EXECUTION_PLAN.md` is preserved as the older prior plan, `NEXT_20_BIG_WINS_EXECUTION_PLAN.md` is the preserved additive-wave closeout plan, and `NEXT_20_BIG_WINS_REGISTRY.yaml` is the machine-readable closeout registry that validators and downstream mirrors can consume directly.

## Active Chummer repos

### `chummer6-design`

Lead-designer repo. Owns cross-repo canonical design truth.

### `chummer6-core`

Deterministic rules/runtime engine. Owns engine truth, explain canon, reducer truth, runtime bundles, and engine contracts.

### `chummer6-ui`

Workbench/browser/desktop product head. Owns builders, inspectors, compare tools, moderation/admin UX, large-screen operator flows, desktop installer recipes, desktop updater integration, desktop apply helpers, and in-app feedback/bug/crash entry points.

### `chummer6-mobile`

Player and GM play-mode shell. Owns mobile/PWA/session UX, offline ledger, sync client, and play-safe live-session surfaces.

### `chummer6-hub`

Hosted orchestration and community plane. Owns identity mapping, user/community accounts, generic groups and memberships, sponsorship/guided-contribution UX, fact/reward/entitlement ledgers, public landing/home projection for `chummer.run`, play API aggregation, relay, approvals, memory, Coach/Spider/Director orchestration, support-case and help surfaces, and hosted service policy. The next major product sequencing rule is Hub-first: account/group/ledger backbone before more guided-contribution-specific Fleet product behavior.

### `chummer6-ui-kit`

Shared design system package. Owns tokens, themes, shell primitives, accessibility primitives, and Chummer-specific reusable UI components.

### `chummer6-hub-registry`

Artifact catalog and publication system. Owns immutable artifacts, publication workflows, release channels, desktop release heads, install/update truth, reviews, compatibility, and runtime-bundle head metadata.

### `chummer6-media-factory`

Dedicated media execution plant. Owns render jobs, previews, manifests, asset lifecycle, and provider isolation for documents, portraits, and bounded video.

## Reference-only repo

### `chummer5a`

Legacy/oracle repo. Used for migration, regression fixtures, and compatibility reference. It is not the vNext product lane.

## Adjacent repos

These inform the program but are not part of the main release train:

* `fleet` — worker orchestration/control plane, mirrored from this repo for execution policy, parity automation, queue synthesis, release orchestration, and signing/notarization evidence
* `executive-assistant` — governed assistant runtime and synthesis/petition reference pattern, including proactive horizon scans, human-edit reflection, bounded replanning, interruption-budget throttling, and explicit design-governance skills such as `design_petition`, `design_synthesis`, and `mirror_status_brief`; repo scope lives in `projects/executive-assistant.md`
* `Chummer6` — downstream public guide and Horizons explainer repo; useful for public storytelling, but not canonical design truth

## Current program priorities

1. Keep canonical design files concise, machine-readable where useful, and clearly above operational evidence noise.
2. Keep Hub’s user/group/ledger/sponsorship model canonical so community participation, premium bursts, and later GM-group tooling all grow from one reusable platform.
3. Maintain Fleet’s cheap-first execution plane and premium-burst policy through mirrored design truth rather than repo-local invention.
4. Give workers a legal petition path when the blueprint is missing a seam, synthesize repeated findings before they become queue truth, and route whole-product signal clusters through the product-governor loop instead of ad hoc operator intuition.
5. Treat future repo work as additive product evolution, not split-wave cleanup or contract-canon repair.
6. Keep sponsored participation generic: Hub grows the reusable user/group/ledger platform first, and Fleet stays the worker execution plane underneath it.
7. Keep `chummer.run` as the product front door and proof shelf, while `Chummer6` remains the deeper downstream explainer.
8. Keep release/build/install/update truth split cleanly: Core emits runtime bundles, UI emits installer-ready desktop heads plus updater apply logic, Fleet orchestrates the release lane, Registry owns promoted channel truth and feed metadata, and Hub renders downloads from registry state.
9. Keep installs claimable rather than personalized: Hub may bind an install to an account, but shipped desktop artifacts remain canonical signed builds for their release target.

The foundational closure wave is materially finished. The Account-Aware Front Door wave and the Next 20 additive wave are both materially closed on public `main`, with their closeout records in `ACCOUNT_AWARE_FRONT_DOOR_CLOSEOUT.md`, `NEXT_20_BIG_WINS_EXECUTION_PLAN.md`, and `NEXT_20_BIG_WINS_REGISTRY.yaml`. Campaign workspace / GM runboard, rule-environment posture, package-owned campaign contracts, roaming restore, Build Lab handoff UX, Rules Navigator, creator publication posture, and the first organizer/operator layer now count as shipped product surfaces instead of only design intent. Remaining growth tracks such as broader campaign breadth, estate-wide promotion, live production cadence, and broader public-surface adoption now sit on top of finished release-governance and boundary truth instead of reopening it.

`PARTICIPATION_AND_BOOSTER_WORKFLOW.md` is the first-class canon for user language, ownership, state transitions, receipts, recognition, and package/bootstrap truth for the bounded participation lane.

`COMMUNITY_SPONSORSHIP_BACKLOG.md` is the implementation-ordered source for the Hub-first community/accounting wave. It distinguishes what already landed in Hub/Fleet/EA from the remaining durable-storage, convergence, and product-depth deltas.

`PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md`, `FEEDBACK_AND_SIGNAL_OODA_LOOP.md`, and `PRODUCT_HEALTH_SCORECARD.yaml` are the operating loop for turning product reality into governed course correction instead of leaving that work as scattered feedback notes.

`CAMPAIGN_SPINE_AND_CREW_MODEL.md`, `CHARACTER_LIFECYCLE_AND_LIVING_DOSSIER.md`, `PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md`, `SUPPORT_AND_SIGNAL_OODA_LOOP.md`, and `BUILD_LAB_PRODUCT_MODEL.md` are the now-closed additive center-of-gravity wave record: the executable middle between build truth and campaign reality, plus the flagship Build and Explain surfaces that made that middle visible to real users. They are now the baseline for follow-on campaign breadth and promotion work rather than still-open canon debt.

## Non-goal

The immediate goal is not to add endless new features while the architecture is still blurry.

The immediate goal is:

* clean ownership
* package-based contracts
* real split completion
* durable design truth
* repeatable release governance
