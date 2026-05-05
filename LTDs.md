# LTDs

Consolidated inventory of your lifetime services/products, including product tier/plan, ownership status, redemption deadlines, and local workspace integration posture.

Updated: 2026-05-05

## Workspace Integration Tier Guide

- `Tier 1`: actively wired into the local workspace/runtime and ready for operational use
- `Tier 2`: owned and partially wired, referenced, or intentionally parked in the local workspace
- `Tier 3`: owned and tracked, but no active local workspace integration yet
- `Tier 4`: credential captured in local environment, but no active runtime lane or account verification yet

## Non-AppSumo / Other LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `1min.AI` | `Advanced Business Plan` | `12 licenses / 12 accounts` | `Owned` |  | `Tier 1` | Local `.env` key rotation slots plus `scripts/resolve_onemin_ai_key.sh` | Primary and fallback API-key flow is wired locally and kept out of git. Shared browser-login password is seeded in local `.env`. Latest credit refresh on `2026-05-05T08:37:52.125920+00:00` for `ONEMIN_AI_API_KEY` confirmed `12345` remaining credits with the next top-up projected for `2026-03-31T00:00:00Z` (`20000` credits). |
| `Prompting Systems` | `Gold Plan` | `1 account` | `Owned` |  | `Tier 2` | Legacy prompt-refinement adapters, BrowserAct workflow hooks, and visual-director provider hints | Wired as a bounded prompt/style helper for internal guide pipelines; still not a general runtime planner dependency. |
| `ChatPlayground AI` | `Unlimited Plan` | `1 account` | `Owned` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `Soundmadeseen` | `API Access` | `1 key` | `Owned` |  | `Tier 4` | `.env` placeholder/secret tracked locally | API key exists in local `.env`; service-level workflow and account-level verification are still pending. |
| `Emailit` | `Tier 5` | `1 account / 1 key` | `Owned` |  | `Tier 1` | Local `.env` API key plus verified `chummer.run` sender-domain wiring in EA | Transactional Emailit delivery is wired locally, `chummer.run` is verified as a sending domain, and the CodexEA internal-affairs daily summary now sends from `ia@chummer.run`. |
| `AI Magicx` | `Rune Plan` | `1 account` | `Owned` |  | `Tier 1` | `ea/app/services/responses_upstream.py` fallback lane and `ea/app/api/routes/responses.py` `/v1/codex` selectors | Routed as a gated secondary lane for short/overflow paths and audit support where 1min capacity is constrained. |
| `FastestVPN PRO` | `15 Devices` | `1 subscription/account` | `Owned` |  | `Tier 3` | None | Infrastructure/privacy utility, not currently wired into this repo. |
| `OneAir` | `Elite` | `1 account` | `Owned` |  | `Tier 3` | None | Travel utility only; no local runtime integration yet. |
| `Headway` | `Premium` | `1 account` | `Owned` |  | `Tier 3` | None | Knowledge/content utility only; no local runtime integration yet. |
| `VidBoard.ai` | `Tier 5` | `1 account` | `Owned` |  | `Tier 4` | BrowserAct-stored credentials for account access; no active runtime lane yet | Newly tracked LTD; account access exists, but no structured verification run or workspace integration is pinned yet. |
| `Deftform` | `No tier recorded` | `1 account` | `Owned` |  | `Tier 4` | Local `.env` username/password only | Newly tracked account with shared local credentials; plan/tier and structured verification are still pending. |
| `hedy.ai` | `LTD account` | `1 account` | `Owned` |  | `Tier 4` | Local `.env` username/password only | Credentials are stored locally for later browser-driven account access or structured verification; no active runtime lane is wired yet. |
| `Internxt Cloud Storage` | `100TB` | `1 account` | `Owned` |  | `Tier 3` | None | Storage service not currently wired into the workspace. |

## AppSumo LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `ApiX-Drive` | `Plus exclusive / License Tier 3` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no active local runtime integration is verified in this repo yet. |
| `ApproveThis` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct content-template packets for approval-queue reading plus skill-catalog references in external-send flows | Ready for BrowserAct-backed queue reading and approval-lane observation without treating ApproveThis as the internal policy engine. |
| `AvoMap` | `10x code-based` | `10 codes` | `Activated` |  | `Tier 2` | BrowserAct video-renderer scaffold packets archived under `/mnt/pcloud/EA` | All codes redeemed and activated; local integration is still staged, not a verified end-to-end production lane. |
| `BrowserAct` | `Tier 3` | `1 product` | `Activated` |  | `Tier 1` | `browseract.extract_account_facts`, `browseract.extract_account_inventory`, `browseract_extract_then_artifact`, local BrowserAct key slots, and connector-bound account-fact discovery | Plan/Tier and activation status are sourced from BrowserAct-backed inventory extraction; run date remains pending external receipt for audit trail. |
| `ClickRank.ai` | `Tier 5` | `1 account` | `Activated` |  | `Tier 2` | Local `.env` credentials plus live site IDs for `chummer.run` and `myexternalbrain.com` | Tier 5 account, both public domains, and served ClickRank ownership snippets are now live for crawl and AI-search auditing without making ClickRank source of truth. |
| `Crezlo Tours` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 1` | BrowserAct-backed property-tour pipeline, public publishing path, and email delivery scripts | Property ingestion, tour generation, publishing, and delivery are wired in this repo. |
| `Documentation.AI` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Owned for AI-ready Chummer6/Fleet/EA docs, cited assistant answers, `llms.txt`, semantic MDX, and private operator-doc publishing. Promote to `Tier 2` after site allocation, sync wiring, and docs freshness verification are real. |
| `FacePop` | `Tier 5` | `1 account` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Tier 5 is confirmed manually; shared local credentials are stored for later structured verification and browser-driven access. |
| `FineTuning.ai` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Owned for sonic cue packs, Newsreel music beds, recap underscoring, and bounded media-factory render support. Promote to `Tier 2` after a provider adapter, cue-receipt stub, and first media-factory smoke run are verified. |
| `First Book ai` | `License Tier 5` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct-stored credentials for account access; no active runtime lane is verified in this repo yet | Activation is confirmed; browser-driven account access exists, but a production runtime lane is not yet pinned here. |
| `GetNextStep.io` | `Tier 5` | `1 account` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Tier 5 and account identity were seeded manually; local credentials now exist for later structured verification or BrowserAct capture. |
| `ICanpreneur` | `Tier 3` | `1 account` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Tier 3 and account identity were seeded manually; local credentials now exist for later structured verification or BrowserAct capture. |
| `Invoiless` | `1x code-based` | `1 code` | `Activated` |  | `Tier 3` | None | Redeemed and activated; still out of the current hot-path product architecture. |
| `katteb.com` | `10x code-based` | `10 codes` | `Owned` |  | `Tier 4` | Local `.env` username/password only | Newly tracked code-based holding; account credentials are present locally and code activation verification is still pending. |
| `Lunacal` | `Tier 4 (highest AppSumo tier)` | `1 account` | `Activated` |  | `Tier 4` | BrowserAct-stored credentials plus local `.env` username/password; no active runtime lane yet | Highest AppSumo tier is confirmed at `app.lunacal.ai`; BrowserAct and the local env both hold the account credentials for later structured verification. |
| `MarkupGo` | `7x code-based` | `7 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; ready for adapter-first media use when needed. |
| `MetaSurvey` | `Plus exclusive / 3x code-based` | `3 codes` | `Activated` |  | `Tier 2` | BrowserAct content-template packets for survey-results reading | Redeemed and activated; structured feedback collection has staged extraction support, not a verified end-to-end lane. |
| `Mootion` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct video-renderer scaffold packets archived under `/mnt/pcloud/EA` | Activation is confirmed; the current local posture is scaffold-stage workflow generation, not yet a production render lane. |
| `Nonverbia` | `Tier 4` | `1 account` | `Activated` |  | `Tier 2` | BrowserAct-stored credentials for account access; no active runtime lane yet | Official Nonverbia app access is available at `app.nonverbia.com`, and account credentials are stored in BrowserAct for later structured verification. |
| `Paperguide` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no active local runtime integration is verified in this repo yet. |
| `ProductLift.dev` | `License Tier 5` | `1 license` | `Activated` |  | `Tier 4` | Local `.env` username/password and license key only | Owned for public feedback intake, voting, roadmap/changelog projection, and private product-signal capture. Promote to `Tier 2` after domain split, webhook/API signal ingestion, and design-triage mapping are verified. |
| `PeekShot` | `3x code-based` | `3 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; suitable for preview/thumbnail adapter work when wired. |
| `Signitic` | `Tier 4` | `1 account` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Tier 4 and account identity were seeded manually; local credentials now exist for later structured verification or BrowserAct capture. |
| `Teable` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 2` | Referenced historically as a possible projection surface, not active runtime storage | Keep out of the hot-path runtime database role; use only as a curated projection if revived. |
| `Unmixr AI` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no active local runtime integration is verified in this repo yet. |
| `Vizologi` | `Plus exclusive / 4x code-based` | `4 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; retained for strategy/research support only. |

## Summary

- `39` total LTD products tracked
- Multiple-code holdings: `AvoMap`, `katteb.com`, `MarkupGo`, `MetaSurvey`, `PeekShot`, `Vizologi`
- Multiple-account holding: `1min.AI` (`12 licenses / 12 accounts`)

## Discovery Tracking

Use this section to track missing tier/email/account facts discovered through the BrowserAct-backed runtime flow.

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `1min.AI` |  | `manual_seeded` | `local_env` | 2026-05-05T08:37:52.125920+00:00 | API-key rotation slots and the shared browser-login password now exist locally. Latest credit refresh on `2026-05-05T08:37:52.125920+00:00` for `ONEMIN_AI_API_KEY` confirmed `12345` remaining credits with the next top-up projected for `2026-03-31T00:00:00Z` (`20000` credits). |
| `Prompting Systems` |  | `missing` | `manual_inventory` |  | Local prompt-refinement wiring exists; account-level verification still has no BrowserAct discovery run recorded yet. |
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
| `MarkupGo` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `MetaSurvey` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `Mootion` |  | `complete` | `manual_inventory` |  | Plan/Tier: License Tier 3; Status: activated |
| `Nonverbia` |  | `missing` | `manual_inventory` |  | Tier 4 is confirmed manually and credentials are stored in BrowserAct, but no structured account-detail verification run is recorded yet. |
| `Paperguide` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `ProductLift.dev` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-22T00:00:00Z | Tier 5 is confirmed manually and local credentials plus the license key are now seeded for public feedback intake, roadmap/changelog projection, and webhook/API signal mapping; no structured BrowserAct account-detail verification run is recorded yet. |
| `PeekShot` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `Signitic` | `tibor@girschele.com` | `manual_seeded` | `local_env` | 2026-04-20T00:00:00Z | Tier 4 and account email were seeded manually; local credentials now exist and structured verification is still pending. |
| `Teable` | ops@teable.example | `complete` | `browseract_live` | 2026-03-07T00:01:00Z | Plan/Tier: License Tier 4; Status: activated |
| `Unmixr AI` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Vizologi` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |

## Attention Items

`katteb.com` is now tracked as a 10-code holding but still needs redemption/activation verification.

## Notes

- The Codex session skill list is not the LTD source of truth; skills are local agent capabilities, while this file tracks your external services/accounts.
- Product/deal tier (`License Tier 3`, `Gold Plan`, `Elite`, etc.) is separate from the workspace integration tier used to describe local wiring posture.
- Secrets are intentionally omitted here; only inventory, status, deadlines, and local integration contracts are documented.
- BrowserAct inventory artifacts can refresh the `## Discovery Tracking` table, `Updated:` stamp, and total-count summary through `bash scripts/refresh_ltds_from_inventory.sh --input <inventory.json> --write` when a fresh structured inventory payload is available.
- If the local EA API and BrowserAct binding are already configured, `bash scripts/refresh_ltds_via_api.sh --binding-id <browseract-binding-id> --service-name BrowserAct --service-name Teable --write` can execute the `ltd_inventory_refresh` skill and rewrite this file without manually exporting the intermediate JSON first.
