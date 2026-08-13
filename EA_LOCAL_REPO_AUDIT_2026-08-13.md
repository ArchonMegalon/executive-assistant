# EA local-repo audit

Date: 2026-08-13 (Europe/Vienna)
Repo: `/docker/EA`
Observed HEAD: `e2c68e9b` (`feat(voice): prefer governed Unmixr account tiers`)
`origin/main`: `fed3560b` (`Close remaining EA baseline failures`)
Status: operator snapshot, not product canon, not a release receipt

This file records a read-only audit of the local Executive Assistant worktree. It is not Chummer design truth, not Memorial release authority, and not proof that any LTD is live. Generated design/studio receipts that disagree with this snapshot remain generated receipts.

The audit did not reset, clean, rebase, commit, or merge. It did not run the full test suite. vexp MCP was down in the auditing session, so context came from git, process, Docker, and file inspection.

## Review checklist

| Check | Result |
| --- | --- |
| Canon fit | Fail. Dirty generated design/release artifacts and an unpublished `LTDs.md` inventory update sit in the worktree. They must not be treated as Chummer canon. |
| Boundary fit | Pass with notes. New Emailit / FastestVPN / VocalLab bindings stay non-executable in the generic registry. Emailit source-of-truth language is EA-lane scoped, not Hub/Fleet ownership. |
| Telemetry / runtime fit | Fail. Three different revisions are in play, generated deploy receipts are 7 days stale, and live env does not match the unpublished LTD claims. |
| Mirror fit | Fail. `.codex-design/product/*` and `.codex-studio/published/*` are dirty and still being rewritten by the live OODA loop. |
| Required design follow-up | No new canon petition. Implementation of already-written LTD mesh design is still missing (capacity scheduler, blast-radius classifier, proof-debt register, vexp opportunity index). |

## Concurrent writers

At audit time another Codex session was live with cwd `/docker/EA`:

- Session `019fd689-15a3-7102-9ac3-290d5f0fc8fb`
- It was finishing a Memorial VocalLab cutover in `/docker/Memorial`, not editing EA source
- Memorial HEAD was `661eb56` (`Remove retired Unmixr voice reference`), 5 commits ahead of Memorial `origin/main`
- EA `NEXT_SESSION_HANDOFF.md` still pins Memorial to `bfaa03a8`. That handoff is stale relative to that agent

Other live writers against this tree:

- `ea-proactive-ooda` rewrites `.codex-studio/published/*.generated.json` on a 15-minute loop
- vexp was reindexing (`.vexp/index.lock` live)
- `ea/app` and `scripts` are bind-mounted read-only into `ea-api`, so uncommitted Python is already the live API code

Do not reset, clean, or fold unrelated dirty files into a release slice. The current handoff already forbids that.

## Git posture

- Branch: `main`, one commit ahead and one behind `origin/main`
- Merge-base: `5bdc11f7`
- The two diverging commits do not touch the same source files. `git merge-tree` auto-merges them. A rebase will still fight the dirty `.vexp/manifest.json`, which changed on both sides
- 47 modified files, 0 staged, 0 untracked
- Source delta excluding generated files: 27 files, +1738 / -133
- Full dirty delta including generated files: +3170 / -1146
- 10 stashes. Highest-risk name: `stash@{0}` `wip unsafe manfred clone lane before live deploy 20260725`
- 29 prunable leftover worktrees
- Stale `.git/REBASE_HEAD` from 2026-07-27 (`292dc728`). No in-progress rebase directory

## What the unpublished work actually is

Three honest lanes, plus generated-file churn.

### 1. Emailit kill switch

- `EA_EMAILIT_DELIVERY_ENABLED` now fails closed in `registration_email.py` and onboarding
- Registry binding `emailit` is visible and `executable=False`
- New LTD lane `emailit_transactional_delivery`
- Tests cover kill-switch, missing key, and register-start link-only fallback

Live gap: `EMAILIT_API_KEY` is set in `ea-api` and the kill switch is unset, so delivery is on. That matches the new default (key present means enabled).

### 2. FastestVPN Switzerland transport

- New `ea-fastestvpn-proxy-ch` service, Switzerland `*.ovpn` glob, host port 9315
- Dockerfile pinned to `alpine:3.20@sha256:…`
- `.dockerignore` now includes `docker/fastestvpn-proxy/**`
- `scripts/ea_live_ops.py` adds configured-proxy preflight, country check, secret-safe receipt fields, and Cloudflare 1015 / 429 cooldown
- Tests fail closed when the proxy is missing, unreachable, or the wrong country

Live gap: running `ea-api` / `ea-worker` / `ea-scheduler` were started with `docker-compose.yml` + `docker-compose.cloudflared.yml` only. They have empty `ONEMIN_DIRECT_API_PROXY_SERVER`. The CH sidecar is healthy, but the core API is not using it.

`ea-whatsapp-web-action-processor` still points at `ea-fastestvpn-proxy` / `-ie` / `-nl`. Those sidecars are not running. Only `-ch` is up.

The unpublished compose overlay also makes `ea-api` / worker / scheduler wait for the CH sidecar to be healthy. Applying that overlay later is a new hard dependency.

### 3. VocalLab visibility, not execution

- Registry key `vocallab` plus `VoiceLab` aliases
- Capabilities `voice_inventory` and `voice_render` are `executable=False`
- Schema parser updated for the live paginated voice payload
- ID regex loosened from `[A-Za-z0-9._:-]` to any non-control 1–256 character string
- The old “voice id must not appear in name” leak check was removed
- `LTDs.md` now marks VocalLab discovery `complete`

Live gap: `VOCALLAB_API_KEY` in `ea-api` is set but empty. The LTD row claims a dedicated EA key passed a 269-voice inventory check. That proof is not present in this container. A mode-`0600` host key exists under `config/` and must stay out of git.

### 4. Generated / index churn

Dirty and still moving at audit time:

- `.codex-studio/published/ea_proactive_ooda_*.generated.json`
- `.codex-studio/published/ea_google_workspace_oauth_readiness.generated.json`
- `.codex-studio/published/ea_operator_action_required_digest.generated.json`
- older 2026-08-06 receipts: deploy context, release authority, release manifest, flagship gate, weekly pulse, Telegram, Teable, Alexa, SBOM

Those 2026-08-06 receipts still claim commit `cd318f92`. Runtime and git HEAD are `e2c68e9`. Origin is `fed3560`. Do not promote from those receipts.

## Runtime vs worktree

| Surface | Revision / state |
| --- | --- |
| Worktree HEAD | `e2c68e9` plus 47 dirty files |
| `origin/main` | `fed3560` |
| `ea-api` `EA_SOURCE_REVISION` | `e2c68e9` |
| `ea-api` image | `ea-runtime:latest`, created 2026-08-12 13:45Z |
| Deploy / release generated JSON | `cd318f92` from 2026-08-06 |
| Bind mounts | `ea/app` → `/app/app`, `scripts` → `/app/scripts` |
| Compose on `ea-api` | `docker-compose.yml` + `docker-compose.cloudflared.yml` (no FastestVPN overlay) |
| OODA | enabled; gold claim blocked; 1 actionable item; approval capture pending |
| Google Workspace OAuth receipt | `ready_retry_required` |
| Continuous-improvement goal | `blocked_real_world_acceptance` (WhatsApp audiobook live receipt), dated 2026-08-06 |
| Office-loop goal | `ready_local_evidence`, generated 2026-07-07, next action Google reconnect |

`ea-api`, `ea-worker`, `ea-scheduler`, `ea-proactive-ooda`, `ea-whatsapp-web-action-processor`, and `ea-fastestvpn-proxy-ch` were healthy.

## Findings

### P1 — do not collide

1. Shared dirty tree with a live Memorial agent and a live OODA writer.
2. Uncommitted Emailit, VocalLab schema, and live-ops proxy code is already production-mounted.
3. Triple revision lie: runtime `e2c68e9`, origin `fed3560`, deploy/release receipts `cd318f92`.

### P1 — honesty / boundary

4. VocalLab LTD `complete` vs empty runtime key. Keep VocalLab non-executable until a dedicated non-empty EA key is actually in this runtime.
5. LTD critical-entry and flagship-subset matchers were loosened to accept alternate evidence tokens. A green aggregate means “verified or blocked,” not “every paid lane is live.”
6. VocalLab schema is looser. Broader IDs and removal of the id-in-name check increase the chance a private provider id lands in operator-visible names.

### P2 — deploy / transport

7. CH proxy is running but not wired to core API/worker/scheduler. WhatsApp still names three proxies that are down.
8. Emailit is live-on by default because the key is present and the new kill switch is unset.
9. FastestVPN overlay, if applied later, hard-gates API startup on the CH sidecar.

### P2 — hygiene

10. Stale `.git/REBASE_HEAD` from 2026-07-27
11. 29 prunable worktrees
12. 10 stashes, including an explicit unsafe Manfred clone lane
13. Handoff Memorial SHA `bfaa03a8` is behind the other agent’s `661eb56`

## What is in good shape

- Registry keeps Emailit, FastestVPN, and VocalLab non-executable
- Emailit kill switch is fail-closed in code and tested
- FastestVPN receipts are designed not to emit credentials or exit IPs
- Live-ops configured-proxy mode fails closed without a reachable proxy
- Historical `MANFRED_MEMORIAL_FLAGSHIP_RELEASE_GATE.md` is marked superseded
- `origin/main`’s baseline fix (Telegram property-theme strip, OODA delivery-guard fallback, active-media receipt arg) does not overlap the unpublished EA source files

## Design vs implementation

| Layer | Count | What it actually is |
| --- | --- | --- |
| `LTDs.md` inventory | 61 services | Prose inventory + discovery table. Updated locally on 2026-08-12. |
| `ltd_provider_governance.py` lanes | 20 | Contract objects + string/file-presence checks. New: Emailit, FastestVPN. |
| Generic provider registry | 19 keys | Visibility / credential-env map. New: `emailit`, `fastestvpn`, `vocallab`. |
| Live executable adapters | far fewer | 1min, Unmixr, Emailit send, Teable, BrowserAct, Google OAuth, a few mail/outbox scripts |

The unpublished slice is governance visibility, not a new product loop.

### Emailit

Designed as transport only. Implemented: real send adapter, rate bounds, registration kill switch. Default sender/copy in `registration_email.py` is still `property@propertyquarry.com` / “PropertyQuarry”. Outbox and Crezlo/PropertyQuarry tour mail share the same `EMAILIT_API_KEY` and do not honor the new switch.

The new lane text says EA owns eligibility, template, suppression, approval, and closeout. The design contract in `.codex-design/product/EMAILIT_OUTBOUND_DELIVERY_PROVIDER.md` says Hub owns notification truth. Those sentences cannot both be estate-wide.

### FastestVPN

Designed as bounded transport for approved provider probes, Switzerland-only for the 1min direct-API lane. Implemented: CH sidecar, pinned image, secret-safe preflight. Not implemented: attaching that path to `ea-api`, replacing the dead WhatsApp IE/NL pool, or a first-class live-ops transport-status command.

### VocalLab

Designed as the preferred second voice provider for an authentic-Manfred clone after Memorial authority, subject-only derivative, deletion, hearing, and rollback. Implemented: registry aliases, non-executable capabilities, schema parser, host key. Not implemented: a `ProviderLane`, a non-empty runtime key in `ea-api`, or a spend-blocked inventory probe.

The audiobook router can still choose `vocallab` when `performance_direction` and authorities pass. That contradicts “catalog only.”

### OODA / office product

Local office-loop components (brief, queue, ledger, approved actions, evidence) report `pass`. Live daily use and real operator acceptance are false. Gold claim is blocked. Google Workspace is `ready_retry_required`. The office-loop receipt still says `reauthorize_google_workspace_binding` and has not been rematerialized since 2026-07-07.

## Functionality gaps

### 1. The office product is locally green and really unaccepted

Quality tests still require `real_daily_morning_brief_accepted`. Remaining proofs are human acceptance: an OODA packet with routed delivery, weekly signal-to-decision review, closed-loop follow-through. Catalog work cannot close those.

### 2. Google Workspace is the live Observe break

OODA source health at audit time:

- `error_code`: `google_oauth_invalid_grant`
- cooldown was active until `2026-08-13T07:49:49Z`
- next action: reconnect full workspace at `/app/actions/google/connect`
- Google readiness receipt explicitly does not prove signal ingest

Approval capture was hollow: `callback_dir_exists: false`, `checked: false`, while an assistant-grade draft packet was present.

### 3. WhatsApp audiobook is waiting on voice choice, not VocalLab

Continuous-improvement goal:

- `blocked_real_world_acceptance`
- `deliver:whatsapp_audiobook=waiting_voice_choice`
- next action: pair WhatsApp Web sidecar and capture a live delivery receipt

### 4. Audiobook still sounds like joined short TTS

- `EA_AUDIOBOOK_CINEMATIC_NARRATION` defaults on
- `EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS` defaults off
- Unmixr adapter is still short TTS
- dialogue voice still comes from `EA_AUDIOBOOK_UNMIXR_DIALOGUE_VOICE_ID` or a private approved token
- per-segment `dynaudnorm` + `loudnorm` then hard concat is still the mastering path

VocalLab schema work does not implement inline EN/DE quote splits, automatic cast, continuation boundaries, or final-track mastering. AiWriteBook, First Book ai, and YouBooks do not fix listening quality either.

### 5. Cost routing still names an empty provider

Office-loop cost posture:

```text
default / cheap / fast / fallback: onemin -> magixai -> gemini_vortex
```

`LTDs.md` says `AI_MAGICX_API_KEY` is empty. Live order still includes `magixai`.

### 6. LTD runtime catalog is property-shaped

`/v1/ltds/runtime-catalog` specialized action keys:

- `discover_account`
- `create_property_tour`
- `background_remove`
- `image_upscale`
- `delivery_outbox`
- `publish_property_flipbook`

There is no catalog action for morning brief, OODA approval, 1min capacity schedule, VocalLab inventory-only, FastestVPN country proof, Hedy intake, or WorkLLM draft. `ea/app/api/routes/` is still dominated by `landing_*` and PropertyQuarry surfaces.

### 7. Scaffolds that look like product and are not live

Routes exist for Hedy intake, Sendr webhook, FlipLink, governed spatial render, and human tasks. Inventory/design still mark those lanes proof-pending. A route is not a promoted LTD.

### 8. Generated truth ages

| Receipt | Generated | Problem |
| --- | --- | --- |
| Office loop goal | 2026-07-07 | Next action still Google reconnect |
| Continuous-improvement goal | 2026-08-06 | WhatsApp audiobook |
| Deploy / release / flagship | 2026-08-06 | SHA `cd318f92` |
| OODA operator / Google | 2026-08-13 | Live, gold blocked |

## Missed opportunities — functionality

None of these require buying another tool.

1. Reconnect Google and accept one real morning brief.
2. Finish the WhatsApp audiobook canary on Unmixr. Pick a voice, deliver one rights-safe fixture, listen, persist the receipt. Do not insert VocalLab into this path.
3. Make OODA Act real: callback dir, record approval outcome, Teable row, Emailit only after approval.
4. Rematerialize office-loop and deploy receipts on the live HEAD.
5. Drop empty `magixai` from live provider order.
6. Automatic Unmixr dialogue cast. VocalLab is redundancy/Manfred, not the missing cast resolver.
7. Final-track mastering instead of per-segment loudness.
8. Split Emailit senders so EA office notices, PropertyQuarry tours, and Hub lifecycle mail cannot share one kill switch and one default PropertyQuarry From.
9. Wire the CH proxy only to the process that actually refreshes 1min. Drop dead IE/NL references.
10. Hedy as backup Observe source after Google is healthy, or if Google stays broken.
11. WorkLLM public-only workbench already has a 20/20 synthetic canary and a kill switch. Do not feed it Gmail or people memory.
12. FlipLink `manfred-how-this-memorial-works` already has a public publication receipt. Closing CNAME/embed/analytics does not touch Memorial voice.
13. Spend-blocked VocalLab inventory probe so the LTD row is reproducible from `ea-api`.

## LTD integration — four-plane drift

The portfolio is described in four places that do not agree.

| Plane | What it is | Count / posture |
| --- | --- | --- |
| `.codex-design/product/LTD_CAPABILITY_MAP.md` | Design roles: promoted / bounded / parked | Promotes Rybbit, Taja, NextStep, Emailit-as-Hub-mail, Unmixr-as-candidate |
| `.codex-design/product/LTD_UTILIZATION_MATRIX.md` | `use_now` / `pilot` / `park` + named product lanes | 16 `use_now` including MagicFit, MarkupGo, Soundmadeseen |
| `LTDs.md` | Workspace tiers 1–4 + discovery table | 61 services; unpublished VocalLab/FastestVPN `complete` |
| EA `LANES` + registry + runtime catalog | What this repo can actually gate or dispatch | 20 lanes, 19 registry keys, about 6 specialized actions |

### Drift that matters

1. **Emailit truth owner is contradicted.** Design: Hub owns notification truth. Utilization matrix owner: `chummer6-hub`. Unpublished EA lane: EA owns eligibility through closeout. Live default: PropertyQuarry sender and copy. EA may own EA-onboarding mail. It must not absorb Hub lifecycle, Black Ledger digests, and PropertyQuarry product mail under one sentence and one key.

2. **Unmixr is production in EA and still “candidate until proven” in the capability map.** Memorial is moving demo voice to VocalLab because Unmixr deletion is red. Three repos, three stories, one voice problem.

3. **MagicFit is `use_now` in the matrix and Tier 4 in `LTDs.md`.** Extra accounts still need account-use receipts.

4. **VocalLab, FastestVPN, and WorkLLM are absent from the utilization matrix.** Inventory and registry were updated; the design matrix was not.

5. **Design-promoted tools missing from `LTDs.md`:** Rybbit, Taja, SendFox, Flonnect, CutMe Short, Visby, Browserly. Do not implement them from EA.

6. **GetNextStep.io is inventory Tier 4.** Design names NextStep as a primary `approval_gate` beside ApproveThis.

7. **1min has no dedicated governance lane** despite being `use_now`, the cost-router default, and 74 restored slots. That is the largest unused owned capacity.

8. **Runtime catalog does not implement the named product lanes** from the matrix (`release_trust_factory`, `public_trust_shelf`, `black_ledger_media_bakeoff`, `meeting_to_decision`, `no_desktop_onboarding_funnel`, `audio_campaign_memory`, `runsite_walkthrough_artifacts`).

9. **Rafter is supposed to gate every tier promotion.** VocalLab went to discovery `complete` and flagship matchers were loosened with no Rafter false-complete check.

10. **Horizon attachments were never turned into EA petition packets.** EA’s job is petitions and operator aids, not owning nexus-pan, origin-dossier, table-pulse, or runsite. Extra registry aliases are not a substitute.

Current governance lanes:

- `fliplink_document_portal`
- `hedy_meeting_evidence`
- `markupgo_fliplink_premium_delivery`
- `approvethis_external_approval_edge`
- `documentation_ai_publication`
- `unmixr_voice_runtime`
- `emailit_transactional_delivery`
- `fastestvpn_governed_provider_transport`
- `magicfit_media_factory_candidate`
- `poppy_draft_workbench`
- `release_quality_gates`
- `public_signal_ingest`
- `docs_draft_factory`
- `prompt_foundry`
- `aiwritebook_chronicle_studio`
- `subscribr_chummer_script_factory`
- `sendr_ea_growth_outreach`
- `operator_control_plane`
- `video_provider_bakeoff`
- `commercial_ops`

VocalLab is the obvious missing 21st lane: inventory and registry were updated, `LANES` was not.

### Design-named mesh still missing

These files do not exist in the repo:

- `config/ltd_capacity_scheduler.yaml`
- `config/ltd_blast_radius.yaml`
- `config/ltd_capability_router.yaml`
- `.codex-studio/published/LTD_PROOF_DEBT.generated.json`
- `docs/VEXP_LTD_OPPORTUNITY_INDEX.md`
- `scripts/query_ltd_opportunity_index.py`

Also unimplemented: Teable tables for provider status and proof debt; Internxt cold-archive restore drill; Black Ledger production line; public signal stack; AI-search trust lane (Documentation.AI + ClickRank + `llms.txt`).

`scripts/verify_ltd_capability_mesh.py` only checks that files exist.

### Parked LTDs with written candidate lanes

Do these before adding more aliases:

| Cluster | LTD | Next honest step |
| --- | --- | --- |
| Office | Hedy, ApproveThis, NextStep, blipai, MarkupGo | API/webhook/render proof; do not promote on route existence |
| Capacity | 1min scheduler, WorkLLM public workbench, AI Magicx, OMagic | Schedule 1min; promote-or-retire Magicx; discover OMagic accounts |
| Trust | FlipLink embed, Documentation.AI, ClickRank, Rafter | Close known receipts; gate promotions |
| Media | Subscribr, MagicFit extra accounts, YouBooks, First Book | Contracts and account-use receipts, not another voice alias |
| Growth | Sendr, Deftform, Lunacal, Signitic | Sendr webhook exists and runtime is off |
| Archive | Internxt | Monthly restore drill, not hot truth |

## What good looks like

Stop measuring EA by how many LTDs are listed. Measure it by:

1. An operator accepted a real morning brief this week
2. Google Workspace ingest works, or Hedy is a proven backup Observe source
3. One WhatsApp or Telegram audiobook was delivered and listened to
4. OODA can record an approval outcome and send only approved Emailit
5. 1min background jobs have slot and credit receipts
6. Every Tier 1/2 LTD has one next-proof row and one must-not-claim
7. Emailit, Unmixr, and VocalLab each have one owner sentence that Hub, EA, and Memorial all repeat

Until those are true, more registry keys and looser LTD gates are inventory theater.

## Recommended operator sequence

Wait until the Memorial session is no longer writing, then:

1. Re-read `git status` before touching anything
2. Keep generated OODA/studio files out of any commit unless rematerialized on purpose
3. Rebase or merge `fed3560` onto `e2c68e9` after regenerating `.vexp/manifest.json`
4. Split the unpublished work: Emailit kill switch, FastestVPN CH transport, VocalLab visibility/schema, docs/LTD
5. Recreate `ea-api` with the FastestVPN overlay only if the CH lane should actually own 1min traffic
6. Do not treat VocalLab or FastestVPN `complete` rows as Memorial or Manfred release authority

Highest-leverage follow-ups after that:

1. Reauthorize Google Workspace
2. Capture WhatsApp audiobook live delivery
3. Add a VocalLab governance lane that stays non-executable and fails if the claimed runtime key is empty
4. Extend the Emailit kill switch to every sender, or split EA / PropertyQuarry / Hub mail into named lanes
5. Attach the CH proxy to the process that refreshes 1min, and drop dead IE/NL references
6. Materialize `LTD_PROOF_DEBT.generated.json` from Attention Items plus the four-plane drift table
7. Close the pending OODA approval item and rematerialize the 2026-07-07 office-loop receipt
8. Remove `magixai` from live default/fallback order while `AI_MAGICX_API_KEY` is empty

## Remediation receipt — 2026-08-13

This appendix records the work performed against the snapshot above. It does not rewrite the
original observations and is not release authority.

### Closed locally and in the live runtime

- VocalLab now has an explicit catalog-only governance lane. Generic routing remains
  non-executable and all render, clone, top-up, and automatic fallback switches remain off. The
  live GET-only inventory probe passed ping, account, models, and 270 voice rows with zero POSTs;
  the receipt remains intentionally blocked on credential rotation/production eligibility and
  explicit spend authorization.
- The live VocalLab clone row shape is parsed exactly without accepting arbitrary extra fields.
  Private IDs are never rendered as operator labels; an ID found in any label is replaced with a
  neutral catalog label.
- Empty Magicx credentials are removed from the effective provider order. Configured Magicx
  remains available, but an empty slot cannot appear ready.
- Emailit is split into EA-office, PropertyQuarry, and Chummer Hub ownership/sender switches.
  Every sender and outbox path now fails closed; Chummer Hub remains off until it has its own
  product approval.
- The FastestVPN overlay is Switzerland-only, no longer hard-gates normal API startup, binds
  `127.0.0.1:9315`, and is injected only into `ea-api`. Worker, scheduler, and WhatsApp have no
  proxy env. `probe-fastestvpn-transport` verifies this secret-safe live topology and currently
  reports `ready`.
- 1min now has a first-class bounded-capacity governance lane with private credential presence,
  quota/cooldown ceilings, blast-radius rules, review-only receipts, and a background off-switch.
- The LTD operating mesh is materialized: scheduler, blast-radius map, named capability router,
  55-row proof-debt projection, secret-safe capacity status, and a 20/20 vexp opportunity index.
- Teable now has live idempotent `ltd_provider_status` and `ltd_proof_debt` projections. The
  latest no-op reconciliation reports 2 and 55 current rows respectively, exposes no secret
  material, and does not supersede source receipts.
- The Rafter/Pixefy false-complete verifier is now part of `ltd-release-gates`.
- The OODA approval callback directory is created durably on the provider-ledger volume. No
  approval or packet was fabricated.
- The stale `REBASE_HEAD` and 29 dead worktree metadata entries were removed. All 10 real stashes,
  including the unsafe Manfred clone recovery stash, remain preserved.

### Verification

- `make ltd-release-gates`: pass, including critical entries, flagship subset, Rafter/Pixefy,
  22 provider lanes, and the operating mesh.
- Root affected-contract suite: 777 passed. EA VocalLab/router suite: 76 passed.
- Base, Cloudflare, production/WhatsApp, and FastestVPN Compose renders: pass.
- Live `ea-api`, worker, scheduler, OODA, and CH proxy were recreated only where required and
  returned healthy; the public API health endpoint passed.
- `git diff --check`: pass.

### Still honest blockers

- Git remains `main...origin/main [ahead 1, behind 1]` with shared user/concurrent work. No rebase,
  broad commit, cleanup, or release receipt was fabricated. The old deploy/release receipts remain
  non-authoritative until a reviewed clean source is merged and the runtime is rebuilt from it.
- Google Workspace still needs a real account-side reauthorization and one accepted morning brief.
- WhatsApp Web currently requires QR pairing, followed by a real rights-safe audiobook delivery
  and listening decision. The existing 2026-08-06 receipt is stale and cannot authorize release.
- OODA has a durable callback surface but no current packet reference or real operator approval.
  Regenerate a genuine stage packet, then approve or reject it as the operator.
- VocalLab rendering/cloning stays blocked in EA until a dedicated rotated credential and the
  Memorial authority/deletion/hearing receipts are present. The GET-only inventory is not Manfred
  release authority.
