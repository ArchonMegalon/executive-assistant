# LTD Utilization Matrix

This document captures executable use rules for LTD-based capability lanes and keeps the authority model explicit.

The Chummer program uses LTDs only as bounded capability providers:

- Chummer owns product, rules, and release truth.
- EA owns orchestration, receipts, policy, and review.
- LTDs provide bounded adapters, renderers, proofs, and outreach support.
- LTDs do not own product truth, release truth, rules truth, entitlement truth, support truth, publication approval, private campaign truth, or account truth.

## Baseline constraints

| Column | Meaning |
|---|---|
| LTD | Bounded external capability |
| Current tier | `use_now`, `pilot`, `park`, or `avoid` |
| Candidate Chummer lane | First intended lane in which this LTD is used |
| Allowed inputs | Inputs that are safe for this provider |
| Forbidden inputs | Inputs forbidden by policy |
| Proof required | Receipt or verification required before lane use |
| Runtime owner | Repo/team that owns receipts and enforcement |
| Human review required? | `yes` when content quality or safety is user-visible |
| Can publish directly? | Must remain `No` |
| Can own truth? | Must remain `No` |

Default hard rule:

- Can publish directly? `No`
- Can own truth? `No`

## Proposed lane matrix

| LTD | Current tier | Candidate Chummer lane | Allowed inputs | Forbidden inputs | Proof required | Runtime owner | Human review required? |
|---|---|---|---|---|---|---|---|
| 1min.AI | use_now | background_capacity_scheduler, support_concierge | low-risk queue tasks, public copy drafts, public-doc transforms, safe support drafts, media prompt variants | release truth, rules truth, private campaign data, entitlement truth, any direct support decision | provider verification, health/readiness receipt, output hash/receipt, slot + budget accounting | chummer6-hub | yes |
| AI Magicx | pilot | support_concierge, background_capacity_scheduler | short interactive overflow, low-risk assistant replies, alternate phrasing | private campaign data, release truth, rules truth, bulk background jobs | routing key + health check, key presence gate, policy gate, output receipt | chummer6-hub | yes |
| vexp.dev | use_now | cross_repo_opportunity_index, release_trust_factory | repo docs, scripts, receipts, roadmap mappings, provider-boundary references | direct canonical writes, runtime account secrets | repo index freshness proof, query coverage report, stale-receipt scan | chummer6-design | no |
| Teable | use_now | cross_repo_opportunity_index, support_concierge, feedback_to_roadmap, proof_debt_operations | admin intent, projection rows, status summaries, proof debt signals | rule truth, release truth, sensitive campaign truth | table sync and write-audit receipt, projection freshness check, OODA queue heartbeat | chummer6-hub | no |
| BrowserAct | use_now | release_trust_factory, support_concierge | public routes, screenshots, audit evidence | private user/campaign data, product truth, source mutation | provider verification, failure-mode tests, false-complete checks, route proof receipts | chummer6-hub | yes |
| ClickRank | use_now | release_trust_factory, ai_ready_public_docs | public routes, changelog, docs | private incident logs, non-canonical claims | crawl/report proofs, freshness checksum checks | chummer6-design | no |
| Rafter | use_now | release_trust_factory, support_concierge, meeting_to_decision | release receipts, auth flows, approval flows | private campaign data, roadmap truth | approval bypass tests, cross-principal isolation checks, outbound authorization receipts | chummer6-hub | yes |
| Pixefy | use_now | release_trust_factory, public_trust_shelf | public pages, responsive snapshots, UI routes | raw campaign artifacts, private telemetry | responsive visual QA receipts, route coverage evidence | chummer-media-factory | no |
| Documentation.AI | use_now | ai_ready_public_docs, public_trust_shelf | git markdown, release receipts, operator-approved docs | support tickets, incident logs, secrets | projection proof, no private upload proof, markdown freshness checks | chummer6-design | yes |
| FlipLink | use_now | public_trust_shelf | approved public docs, receipts | private data, untrusted source packets | publication dry run, watermark/commercial checks | chummer6-media-factory | yes |
| MarkupGo | use_now | public_trust_shelf, meeting_to_decision, creator_publication_ops | audit records, proof cards, decision packets | private incident logs, secrets, direct publish payloads | rendered packet receipts, human review for support/safety copy | chummer6-media-factory | yes |
| ProductLift | use_now | feedback_to_roadmap, creator_publication_ops | structured survey/feedback signals, roadmap votes | rule truth, release artifacts, user secrets | signal mirror proofs, decision routing receipts | chummer6-hub | no |
| MetaSurvey | pilot | feedback_to_roadmap | feedback forms, structured intake | account secrets, crash stack traces without approval | survey lane smoke checks, schema validation | chummer6-hub | no |
| PayFunnels | pilot | creator_publication_ops | no-benefit trial events | entitlement grants, production billing keys | HMAC test harness, webhook verification | chummer6-hub | no |
| Answerly | pilot | support_concierge | known-issue text, support routing prompts | rules truth, private campaign state, rules ingestion | support draft receipts, operator final approval | chummer6-hub | yes |
| Emailit | use_now | support_concierge, meeting_to_decision, no_desktop_onboarding_funnel | transactional notices, approval followups | raw secrets, unsanitized PII-heavy payloads | send approval receipts, suppression/deletion posture checks | chummer6-hub | no |
| ApproveThis | pilot | meeting_to_decision, feedback_to_roadmap, creator_publication_ops | approval requests, decision packets | secrets, raw support tickets, unscoped actions | approval callback proofs, authorization receipts | chummer6-hub | yes |
| Hedy | pilot | meeting_to_decision | transcript summaries, consented meeting packets | private campaign history, raw recordings without consent | transcript capture proof, privacy boundary checks | chummer6-hub | yes |
| blipai | pilot | meeting_to_decision | operator prompts, voice notes | user secrets, campaign data, decision-critical payloads | proof of capture and storage posture | chummer6-hub | yes |
| Subscribr | pilot | black_ledger_media_bakeoff | approved scripts and briefing packets | raw campaign private data, unreviewed claims | narrative source packet proof, editorial review | chummer-media-factory | yes |
| Unmixr AI | pilot | black_ledger_media_bakeoff, audio_campaign_memory | approved script text, approved story packets | unlicensed raw text, private campaign data | voice selection audit, consent receipt, output checksum | chummer-media-factory | yes |
| MagicFit | use_now | black_ledger_media_bakeoff | approved B-roll briefs | unreviewed sensitive source files, private campaign data | commercial-use/watermark checks, content quality pass | chummer-media-factory | no |
| AvoMap | pilot | black_ledger_media_bakeoff, runsite_walkthrough_artifacts | approved spatial briefs, map overlays | raw sensitive location data without consent | route safety checks, output integrity evidence | chummer-media-factory | no |
| YouBooks | park | public_trust_shelf, black_ledger_media_bakeoff, creator_publication_ops | approved public docs, approved guide/booklet drafts, approved media packets | sourcebook text, unverified commercial-use claims, private campaign data | provider integration contract proof, account capability proof, copyright/privacy clearance | chummer6-hub | no |
| VidBoard.ai | park | black_ledger_media_bakeoff, no_desktop_onboarding_funnel | approved scripts and safe B-roll packages | direct publish control, product truth | commercial-use verification, watermark checks | chummer-media-factory | yes |
| JoggAI | park | black_ledger_media_bakeoff | approved scripts, consented actor briefs | private likeness data, direct publication | likeness safety checks, human review | chummer-media-factory | yes |
| Mootion | park | black_ledger_media_bakeoff | approved scripts, approved shot maps | direct publish control, private likeness data | quality gate and pilot proof | chummer-media-factory | yes |
| Nonverbia | park | black_ledger_media_bakeoff | approved presenter/audio briefs | private campaign data, high-risk likeness | creator review and quality proof | chummer-media-factory | yes |
| PeekShot | use_now | public_trust_shelf, black_ledger_media_bakeoff | approved media, contact-sheet briefs | unapproved source content, secrets | contact-sheet/thumbnail receipt | chummer-media-factory | no |
| FineTuning.ai | park | black_ledger_media_bakeoff | cue metadata, approved audio styles | sourcebook text, private recordings | audio rights proof, export checks | chummer-media-factory | yes |
| Soundmadeseen | use_now | black_ledger_media_bakeoff, audio_campaign_memory | approved scripts, recap copy | direct source mutation, private campaign narratives | rights/commercial proof, sound check | chummer-media-factory | yes |
| Deftform | pilot | no_desktop_onboarding_funnel | public run intake forms, safe application fields | secrets, sensitive campaign history | schema checks, suppression/copy approval | chummer6-hub | yes |
| Lunacal | pilot | no_desktop_onboarding_funnel | scheduling requests, interview slots | normal support queue, sensitive health data | plan/tier verification, consent checks | chummer6-hub | no |
| Sendr | park | no_desktop_onboarding_funnel | approved outreach sequences | direct broadcast, sensitive lists | recipient suppression proof, off-switch | chummer6-hub | yes |
| Signitic | pilot | no_desktop_onboarding_funnel | campaign-safe signatures and signatures metadata | bulk private PII blasts, unsanctioned outbound | verification + brand signature proofs | chummer6-hub | no |
| Crezlo Tours | use_now | runsite_walkthrough_artifacts | approved runsite route maps | secret layouts, unverified gameplay truth | generation delivery receipt | chummer-media-factory | no |
| Pano2VR | park | runsite_walkthrough_artifacts | explorable mission packets | private map secrets, unapproved route exports | migration readiness proof | chummer-media-factory | no |
| Internxt | park | storage_archive | proof artifacts, raw media candidates, backups | production user data, entitlement records | backup integrity and restore drill | operations | no |
| OMagic | park | cross_repo_opportunity_index | account discovery proofs, capability inventory outputs, visual draft candidates, low-risk script variants | private campaign data, unverified capabilities, direct publication | capability inventory proof, account discovery proof, first pilot proof required | chummer6-hub | yes |

## Named product lanes

- `release_trust_factory`
- `public_trust_shelf`
- `black_ledger_media_bakeoff`
- `background_capacity_scheduler`
- `cross_repo_opportunity_index`
- `support_concierge`
- `proof_debt_operations`
- `feedback_to_roadmap`
- `creator_publication_ops`
- `no_desktop_onboarding_funnel`
- `runsite_walkthrough_artifacts`
- `audio_campaign_memory`
- `meeting_to_decision`
- `ai_ready_public_docs`
- `storage_archive`

## Lane outputs and owner policy

- `release_trust_factory` → `RELEASE_TRUST_FACTORY.generated.json` (chummer6-hub)
- `public_trust_shelf` → public trust shelf artifacts and generated proof cards (chummer6-design)
- `black_ledger_media_bakeoff` → `BLACK_LEDGER_PROVIDER_BAKEOFF.generated.json` (chummer6-media-factory)
- `feedback_to_roadmap` → `PUBLIC_SIGNAL_TO_DECISION.generated.json` (chummer6-hub)
- `support_concierge` → support receipt packet and final approved response (chummer6-hub)
- `background_capacity_scheduler` → `LTD_CAPACITY_STATUS.generated.yaml` (chummer6-hub)
- `cross_repo_opportunity_index` → `VEXP_LTD_OPPORTUNITY_INDEX.generated.json` (executive-assistant)
- `proof_debt_operations` → `LTD_PROOF_DEBT.generated.json` (executive-assistant)
- `storage_archive` → archive manifest and restore drill artifacts (operations)
- `meeting_to_decision` → immutable decision packet and approval trail (chummer6-hub)

## Promotion policy

A capability moves forward only if all of the following are present:

- provider verification
- account verification
- rights/commercial-use proof where relevant
- watermark/export proof where relevant
- privacy boundary proof
- input/output hash receipt
- human review receipt where relevant
- off switch and failure-mode tests
- no `can publish directly` and no `can own truth`
