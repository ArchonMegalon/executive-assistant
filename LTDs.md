# LTDs

Consolidated inventory of your lifetime services/products, including product tier/plan, ownership status, redemption deadlines, and local workspace integration posture.

Updated: 2026-06-02

## Workspace Integration Tier Guide

- `Tier 1`: actively wired into the local workspace/runtime and ready for operational use
- `Tier 2`: owned and partially wired, referenced, or intentionally parked in the local workspace
- `Tier 3`: owned and tracked, but no active local workspace integration yet
- `Tier 4`: credential captured in local environment, but no active runtime lane or account verification yet

## Non-AppSumo / Other LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `1min.AI` | `Advanced Business Plan` | `12 licenses / 12 accounts` | `Owned` |  | `Tier 1` | Local `.env` key rotation slots plus `scripts/resolve_onemin_ai_key.sh` | Primary and fallback API-key flow is wired locally and kept out of git. Shared browser-login password is seeded in local `.env`. Latest credit refresh on `2026-06-02T18:17:17.602510+00:00` for `ONEMIN_AI_API_KEY` confirmed `12345` remaining credits with the next top-up projected for `2026-03-31T00:00:00Z` (`20000` credits). |
| `ChatPlayground AI` | `Unlimited Plan` | `1 account` | `Owned` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `Soundmadeseen` | `API Access` | `1 key` | `Owned` |  | `Tier 4` | `.env` placeholder/secret tracked locally | API key exists in local `.env`; service-level workflow and account-level verification are still pending. Candidate newsroom sound-design lane only after rights, cue provenance, and adapter proof exist. |
| `Emailit` | `Tier 5` | `1 account / 1 key` | `Owned` |  | `Tier 1` | Local `.env` API key plus verified `chummer.run` sender-domain wiring in EA | Transactional Emailit delivery is wired locally, `chummer.run` is verified as a sending domain, and the CodexEA internal-affairs daily summary now sends from `ia@chummer.run`. It is also the approved Black Ledger Newsroom delivery lane after episode proof exists. |
| `AI Magicx` | `Rune Plan` | `1 account` | `Owned` |  | `Tier 1` | `ea/app/services/responses_upstream.py` fallback lane and `ea/app/api/routes/responses.py` `/v1/codex` selectors | Routed as a gated secondary lane for short/overflow paths and audit support where 1min capacity is constrained. |
| `FastestVPN PRO` | `15 Devices` | `1 subscription/account` | `Owned` |  | `Tier 3` | None | Infrastructure/privacy utility, not currently wired into this repo. |
| `PayPal API` | `REST API` | `1 account` | `Owned` |  | `Tier 4` | Local `.env` client ID/secret/email only | PayPal API credentials are captured locally for the PropertyQuarry paid-tier lane. No runtime checkout, webhook, or entitlement flow is wired yet. |
| `OneAir` | `Elite` | `1 account` | `Owned` |  | `Tier 3` | None | Travel utility only; no local runtime integration yet. |
| `Headway` | `Premium` | `1 account` | `Owned` |  | `Tier 3` | None | Knowledge/content utility only; no local runtime integration yet. |
| `VidBoard.ai` | `Tier 5` | `1 account` | `Owned` |  | `Tier 4` | BrowserAct-stored credentials for account access; no active runtime lane yet | Candidate photoreal newsroom host/video lane, but still blocked until commercial-use, watermark, duration, and quality verification are captured in newsroom provider proof. |
| `Deftform` | `No tier recorded` | `1 account` | `Owned` |  | `Tier 4` | Local `.env` username/password only | Newly tracked account with shared local credentials; plan/tier and structured verification are still pending. |
| `hedy.ai` | `LTD account` | `1 account` | `Owned` |  | `Tier 4` | Local `.env` username/password only | Credentials are stored locally for later browser-driven account access or structured verification; no active runtime lane is wired yet. |
| `Internxt Cloud Storage` | `100TB` | `1 account` | `Owned` |  | `Tier 3` | None | Storage service not currently wired into the workspace. |

## AppSumo LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `ApiX-Drive` | `Plus exclusive / License Tier 3` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no active local runtime integration is verified in this repo yet. |
| `Answerly.io` | `Tier 5` | `1 account` | `Activated` |  | `Tier 2` | Local `.env` credentials plus Chummer-bound support-only integration canon, off switches, RuleSafe packet boundary, and Fleet proof receipts | Allowed as a bounded support assistant and optional RuleSafe humanizer only. It remains forbidden as rules truth, sourcebook backend, or private campaign processor until explicit license receipts say otherwise. |
| `ApproveThis` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct content-template packets for approval-queue reading plus skill-catalog references in external-send flows | Ready for BrowserAct-backed queue reading and approval-lane observation without treating ApproveThis as the internal policy engine. |
| `AvoMap` | `10x code-based` | `10 codes` | `Activated` |  | `Tier 2` | BrowserAct video-renderer scaffold packets archived under `/mnt/pcloud/EA` | All codes redeemed and activated; local integration is still staged, not a verified end-to-end production lane. Candidate newsroom map/B-roll lane only. |
| `BrowserAct` | `Tier 3` | `1 product` | `Activated` |  | `Tier 1` | `browseract.extract_account_facts`, `browseract.extract_account_inventory`, `browseract_extract_then_artifact`, local BrowserAct key slots, and connector-bound account-fact discovery | Plan/Tier and activation status are sourced from BrowserAct-backed inventory extraction; run date remains pending external receipt for audit trail. BrowserAct is the verified newsroom provider-proof and route-QA lane, not editorial truth. |
| `ClickRank.ai` | `Tier 5` | `1 account` | `Activated` |  | `Tier 2` | Local `.env` credentials plus live site IDs for `chummer.run` and `myexternalbrain.com` | Tier 5 account, both public domains, and served ClickRank ownership snippets are now live for crawl and AI-search auditing without making ClickRank source of truth. |
| `Crezlo Tours` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 1` | BrowserAct-backed property-tour pipeline, public publishing path, and email delivery scripts | Property ingestion, tour generation, publishing, and delivery are wired in this repo. |
| `Documentation.AI` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Owned for AI-ready Chummer6/Fleet/EA docs, cited assistant answers, `llms.txt`, semantic MDX, and private operator-doc publishing. Promote to `Tier 2` after site allocation, sync wiring, and docs freshness verification are real. |
| `FacePop` | `Tier 5` | `1 account` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Tier 5 is confirmed manually; shared local credentials are stored for later structured verification and browser-driven access. |
| `FineTuning.ai` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Owned for sonic cue packs, Newsreel music beds, recap underscoring, and bounded media-factory render support. Candidate newsroom cue-bed lane only until adapter, rights, and smoke proof exist. |
| `First Book ai` | `License Tier 5` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct-stored credentials for account access; no active runtime lane is verified in this repo yet | Activation is confirmed; browser-driven account access exists, but a production runtime lane is not yet pinned here. |
| `GetNextStep.io` | `Tier 5` | `1 account` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Tier 5 and account identity were seeded manually; local credentials now exist for later structured verification or BrowserAct capture. |
| `ICanpreneur` | `Tier 3` | `1 account` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Tier 3 and account identity were seeded manually; local credentials now exist for later structured verification or BrowserAct capture. |
| `Invoiless` | `1x code-based` | `1 code` | `Activated` |  | `Tier 3` | None | Redeemed and activated; still out of the current hot-path product architecture. |
| `katteb.com` | `10x code-based` | `10 codes` | `Owned` |  | `Tier 4` | Local `.env` username/password only | Newly tracked code-based holding; account credentials are present locally and code activation verification is still pending. |
| `Lunacal` | `Tier 4 (highest AppSumo tier)` | `1 account` | `Activated` |  | `Tier 4` | BrowserAct-stored credentials plus local `.env` username/password; no active runtime lane yet | Highest AppSumo tier is confirmed at `app.lunacal.ai`; BrowserAct and the local env both hold the account credentials for later structured verification. |
| `MagicFit` | `License Tier 5` | `2 accounts` | `Owned` |  | `Tier 4` | Local `.env` credentials for the newly seeded account; candidate `MagicFitProviderAdapter` for `chummer6-media-factory` after provider verification | Acquired for Chummer6 promo-video recovery and Black Ledger Newsroom provider bake-off. Candidate uses: text-to-video/image-to-video B-roll, faction promo scenes, social derivatives, and short photoreal anchor tests. It may render candidate assets only; it must not publish directly, own editorial/product truth, or serve as product proof. Promote only after provider verification, commercial-use/watermark/export/credit receipts, motion/people-action scores, public-safety scan, and human creative review. Accounts reported as `tibor.girschele@gmail.com` and `the.girscheles@gmail.com`; the latter is now seeded locally for runtime verification. |
| `MarkupGo` | `7x code-based` | `7 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; suitable for newsroom poster frames, proof cards, and contact sheets after adapter proof lands. |
| `MetaSurvey` | `Plus exclusive / 3x code-based` | `3 codes` | `Activated` |  | `Tier 2` | BrowserAct content-template packets for survey-results reading | Redeemed and activated; structured feedback collection has staged extraction support, not a verified end-to-end lane. |
| `Mootion` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct video-renderer scaffold packets archived under `/mnt/pcloud/EA` | Activation is confirmed; the current local posture is scaffold-stage workflow generation, not yet a production render lane. Candidate newsroom host/motion lane only until verified. |
| `Nonverbia` | `Tier 4` | `1 account` | `Activated` |  | `Tier 2` | BrowserAct-stored credentials for account access; no active runtime lane yet | Official Nonverbia app access is available at `app.nonverbia.com`, and account credentials are stored in BrowserAct for later structured verification. Candidate newsroom presenter lane only until verified. |
| `Paperguide` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no active local runtime integration is verified in this repo yet. |
| `Pixefy` | `License Tier 3 / highest AppSumo tier` | `1 account` | `Owned` |  | `Tier 2` | Fleet responsive visual QA gate verified | Acquired as responsive visual QA for `chummer.run`, PWA, Black Ledger, downloads/status, newsroom, faction onboarding, and support pages. Fleet proof: `fleet/_completion/pixefy/PIXEFY_PROVIDER_VERIFICATION.generated.json` and `fleet/_completion/pixefy/PIXEFY_RESPONSIVE_VISUAL_QA.generated.json`. Pixefy is not a Media Factory renderer and must not be product truth. |
| `Rafter` | `License Tier 3 / highest AppSumo tier` | `1 account` | `Owned` |  | `Tier 2` | Fleet security/proof gate verified | Acquired as Chummer6 release-security and false-complete prevention infrastructure. Fleet proof: `fleet/_completion/rafter/RAFTER_PROVIDER_VERIFICATION.generated.json` and `fleet/_completion/rafter/RAFTER_SECURITY_GOLD_GATE.generated.json`. Rafter may produce auxiliary security evidence only; it must not own product truth, release truth, roadmap truth, or publish changes. |
| `ProductLift.dev` | `License Tier 5` | `1 license` | `Activated` |  | `Tier 2` | Local `.env` credentials plus dry-run Chummer signal-mirror adapters and receipts | Use on `chummer.run` as the public signal mirror for feedback, voting, roadmap, changelog, package follow, and Karma Forge signal projection, while Chummer remains the source of truth. |
| `PayFunnels` | `Tier 3` | `1 account` | `Owned` |  | `Tier 3` | Bounded `$1 Billing Test` adapter with HMAC webhook verification and no-op entitlement ledger | Test-only billing plumbing. The only enabled product is `payfunnels_test_payment_1usd_v1`: $1 one-time, no benefits, no premium features, no render credits, no special access, and no feature unlocks. PayFunnels is not entitlement truth and no webhook secrets are committed. |
| `Prompt Architects` | `Tier 4` | `1 account` | `Activated` |  | `Tier 4` | `PROMPTING_SYSTEMS_API_KEY` in local `.env`; governed Prompt Foundry Accelerator is integrated for template seed/operator assist | AppSumo Tier 4 capture is confirmed for 20 team members, 20,000 prompts/month, unlimited prompt history/context, JSON/image/video prompt support, Chrome/sidebar/hotkeys, template tags, refine/shorten modes, and claimed MCP. Runtime GM assist remains disabled until API/MCP automation, export semantics, retention, and tenant isolation are verified. |
| `PeekShot` | `3x code-based` | `3 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; suitable for newsroom thumbnail, poster, and contact-sheet adapter work when wired. |
| `Signitic` | `Tier 4` | `1 account` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Tier 4 and account identity were seeded manually; local credentials now exist for later structured verification or BrowserAct capture. |
| `Syllabbles` | `Max tier` | `1 account` | `Activated` |  | `Tier 2` | Local `.env` credentials plus dispatch-draft adapter, template, and dry-run tests | Use as a Black Ledger Dispatch draft workbench only. Drafts stay non-authoritative until Chummer gates and publishes them. |
| `blipai.app` | `Max tier` | `1 account` | `Owned` |  | `Tier 2` | Local `.env` credentials/token plus operator-capture packet transform and tests | Use for operator voice capture, prompt capture, and audit-note capture. Never publish directly from this lane. |
| `Teable` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 2` | Local API key plus projection adapter and dry-run sync receipt | Use only as a curated operator projection surface for product signals, dispatches, tick-news delivery, package pressure, adapter readiness, and newsroom production tracking. |
| `Unmixr AI` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 3` | None | Candidate newsroom narration cleanup / voice polish lane, but no active local runtime integration is verified in this repo yet. |
| `Vizologi` | `Plus exclusive / 4x code-based` | `4 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; retained for strategy/research support only. |

## Summary

- `46` total LTD products tracked
- Multiple-code holdings: `AvoMap`, `katteb.com`, `MarkupGo`, `MetaSurvey`, `PeekShot`, `Vizologi`
- Multiple-account holding: `1min.AI` (`12 licenses / 12 accounts`)

## Discovery Tracking

Use this section to track missing tier/email/account facts discovered through the BrowserAct-backed runtime flow.

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `1min.AI` |  | `manual_seeded` | `local_env_browseract_refresh` | 2026-06-02T18:17:17.602510+00:00 | API-key rotation slots and the shared browser-login password now exist locally. Latest credit refresh on `2026-06-02T18:17:17.602510+00:00` for `ONEMIN_AI_API_KEY` confirmed `12345` remaining credits with the next top-up projected for `2026-03-31T00:00:00Z` (`20000` credits). |
| `PayFunnels` |  | `manual_seeded` | `payfunnels_test_billing_receipts` | 2026-06-01T00:00:00Z | Tier 3 is tracked as a test-only billing adapter. Receipts verify the $1 no-benefit checkout copy, acknowledgement gate, webhook signature/idempotency checks, receipt ledger, no-op entitlement ledger, refund path, and security review. |
| `PayPal API` | `tibor.girschele@gmail.com` | `manual_seeded` | `local_env` | 2026-06-02T00:00:00Z | Client ID, secret, and account email are now stored locally. Checkout, webhook verification, and entitlement mapping still need implementation. |
| `Prompt Architects` |  | `manual_seeded` | `local_env + prompt_foundry_receipts` | 2026-06-01T20:54:48.618432+00:00 | Local `.env` contains the AppSumo API key slot for `PROMPTING_SYSTEMS_API_KEY`; Prompt Foundry integration receipts verify Tier 4 capability capture, template seed/operator assist, usage metering, privacy boundaries, MagicFit bridge, and runtime GM assist disabled pending API/MCP/privacy/export proof. |
| `ChatPlayground AI` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Soundmadeseen` |  | `complete` | `local_env` |  | API key captured locally; plan/tier and account email still need discovery. |
| `Emailit` |  | `manual_seeded` | `emailit_api_live` | 2026-05-01T05:00:00Z | Tier 5 is noted manually; the local API key is live, `chummer.run` is verified as an Emailit sending domain, and `ia@chummer.run` is wired as the CodexEA internal-affairs sender. |
| `AI Magicx` |  | `missing` | `manual_inventory` |  | Local overflow-response wiring exists; account-level verification still has no BrowserAct discovery run recorded yet. |
| `FastestVPN PRO` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `OneAir` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Headway` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `VidBoard.ai` | `the.girscheles@gmail.com` | `manual_seeded` | `browseract_local` | 2026-04-14T00:00:00Z | Tier 5 and account email were seeded manually; credentials remain out of git and structured BrowserAct verification is still pending. |
| `Deftform` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-16T09:27:27Z | Account ownership and shared credentials were seeded manually; plan/tier and structured verification are still pending. |
| `FacePop` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-16T09:42:38Z | Tier 5 and shared credentials were seeded manually; structured verification and any BrowserAct capture are still pending. |
| `GetNextStep.io` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-20T00:00:00Z | Tier 5 and account email were seeded manually; local credentials now exist and structured verification is still pending. |
| `ICanpreneur` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-20T00:00:00Z | Tier 3 and account email were seeded manually; local credentials now exist and structured verification is still pending. |
| `hedy.ai` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-02T00:00:00Z | Username/password are stored locally; plan/tier and activation details still need structured verification. |
| `Internxt Cloud Storage` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `ApiX-Drive` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Answerly.io` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-05-19T00:00:00Z | Tier 5 credentials are locally seeded and the Chummer workspace now carries support-only integration boundaries plus fallback/off-switch proof. Live provider verification is still pending before any non-fallback runtime use. |
| `ApproveThis` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `AvoMap` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `BrowserAct` | ops@example.com | `complete` | `browseract_live` | 2026-03-07T00:00:00Z | Plan/Tier: Tier 3; Status: activated |
| `ClickRank.ai` | `the.girscheles@gmail.com` | `complete` | `clickrank_live` | 2026-05-04T07:44:00Z | Tier 5, account email, `chummer.run`, and `myexternalbrain.com` are now present in ClickRank; both public domains serve the expected ownership snippets and the prior ClickRank verification/onboarding gates no longer appear. |
| `Crezlo Tours` |  | `missing` | `manual_inventory` |  | License Tier 4 is confirmed manually and credentials are stored in BrowserAct, but no structured account-detail verification run is recorded yet. |
| `Documentation.AI` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-22T00:00:00Z | Tier 3 is confirmed manually and local credentials are now seeded for AI-ready docs, `llms.txt`, cited assistant answers, and private operator-doc planning; no structured BrowserAct account-detail verification run is recorded yet. |
| `First Book ai` |  | `missing` | `manual_inventory` |  | License Tier 5 is confirmed manually and credentials are stored in BrowserAct, but no structured account-detail verification run is recorded yet. |
| `FineTuning.ai` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-22T00:00:00Z | Tier 3 and shared credentials were seeded manually; sonic cue/media-factory verification and any future API-key capture are still pending. |
| `Invoiless` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `katteb.com` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-24T00:00:00Z | 10-code holding is tracked; account credentials are seeded locally and redemption/activation verification is still pending. |
| `Lunacal` | `the.girscheles@gmail.com` | `manual_seeded` | `browseract_local` | 2026-04-16T09:16:24Z | Highest AppSumo tier and account email were seeded manually; credentials are stored locally and in BrowserAct; structured verification is still pending. |
| `MagicFit` | `tibor.girschele@gmail.com`; `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-05-31T00:00:00Z | Two License Tier 5 accounts are now tracked. The newer `the.girscheles@gmail.com` account credentials are stored in local EA `.env` for structured BrowserAct/provider verification. Account capability capture, commercial-use/watermark/export checks, monthly-credit confirmation, and Media Factory adapter proof are still pending before runtime use. |
| `MarkupGo` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `MetaSurvey` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `Mootion` |  | `complete` | `manual_inventory` |  | Plan/Tier: License Tier 3; Status: activated |
| `Nonverbia` |  | `missing` | `manual_inventory` |  | Tier 4 is confirmed manually and credentials are stored in BrowserAct, but no structured account-detail verification run is recorded yet. |
| `Paperguide` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Pixefy` | `the.girscheles@gmail.com` | `manual_seeded` | `fleet_verified` | 2026-05-29T20:16:00Z | Highest tier / License Tier 3 was reported by the user. Fleet provider verification and responsive visual-QA gate now pass; see `fleet/_completion/pixefy/PIXEFY_PROVIDER_VERIFICATION.generated.json` and `fleet/_completion/pixefy/PIXEFY_RESPONSIVE_VISUAL_QA.generated.json`. |
| `ProductLift.dev` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-22T00:00:00Z | Tier 5 is confirmed manually and local credentials plus the license key are now seeded for public feedback intake, roadmap/changelog projection, and webhook/API signal mapping; no structured BrowserAct account-detail verification run is recorded yet. |
| `Rafter` | `the.girscheles@gmail.com` | `manual_seeded` | `fleet_verified` | 2026-05-29T20:16:00Z | Highest tier / License Tier 3 was reported by the user. Fleet provider verification and security/proof gate now pass; see `fleet/_completion/rafter/RAFTER_PROVIDER_VERIFICATION.generated.json` and `fleet/_completion/rafter/RAFTER_SECURITY_GOLD_GATE.generated.json`. |
| `PeekShot` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `Signitic` | `tibor@girschele.com` | `manual_seeded` | `local_env` | 2026-04-20T00:00:00Z | Tier 4 and account email were seeded manually; local credentials now exist and structured verification is still pending. |
| `Syllabbles` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-05-14T00:00:00Z | Tier 3 and shared credentials were seeded manually for the Black Ledger dispatch draft lane; structured verification and any BrowserAct capture are still pending. |
| `blipai.app` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-05-14T00:00:00Z | Shared credentials are now seeded locally; plan/tier and structured verification are still pending. |
| `Teable` | ops@teable.example | `complete` | `browseract_live` | 2026-03-07T00:01:00Z | Plan/Tier: License Tier 4; Status: activated |
| `Unmixr AI` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Vizologi` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |

## Attention Items

`katteb.com` is now tracked as a 10-code holding but still needs redemption/activation verification.

`Pixefy` highest tier is tracked and Fleet responsive-visual-QA provider verification now passes. It remains an auxiliary QA gate, not product truth.

`Rafter` highest tier is now reported and Fleet security/proof provider verification now passes. It remains an auxiliary QA gate, not release truth.

`MagicFit` now has two tracked License Tier 5 accounts, with the newer account seeded in local EA `.env`; provider verification is still required before it can become a Chummer6 Media Factory render lane.

## Notes

- The Codex session skill list is not the LTD source of truth; skills are local agent capabilities, while this file tracks your external services/accounts.
- Product/deal tier (`License Tier 3`, `Gold Plan`, `Elite`, etc.) is separate from the workspace integration tier used to describe local wiring posture.
- Secrets are intentionally omitted here; only inventory, status, deadlines, and local integration contracts are documented.
- BrowserAct inventory artifacts can refresh the `## Discovery Tracking` table, `Updated:` stamp, and total-count summary through `bash scripts/refresh_ltds_from_inventory.sh --input <inventory.json> --write` when a fresh structured inventory payload is available.
- If the local EA API and BrowserAct binding are already configured, `bash scripts/refresh_ltds_via_api.sh --binding-id <browseract-binding-id> --service-name BrowserAct --service-name Teable --write` can execute the `ltd_inventory_refresh` skill and rewrite this file without manually exporting the intermediate JSON first.
