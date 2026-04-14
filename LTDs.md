# LTDs

Consolidated inventory of your lifetime services/products, including product tier/plan, ownership status, redemption deadlines, and local workspace integration posture.

Updated: 2026-04-14

## Workspace Integration Tier Guide

- `Tier 1`: actively wired into the local workspace/runtime and ready for operational use
- `Tier 2`: owned and partially wired, referenced, or intentionally parked in the local workspace
- `Tier 3`: owned and tracked, but no active local workspace integration yet
- `Tier 4`: credential captured in local environment, but no active runtime lane or account verification yet

## Non-AppSumo / Other LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `1min.AI` | `Advanced Business Plan` | `12 licenses / 12 accounts` | `Owned` |  | `Tier 1` | Local `.env` key rotation slots plus `scripts/resolve_onemin_ai_key.sh` | Primary and fallback API-key flow is wired locally and kept out of git. |
| `Prompting Systems` | `Gold Plan` | `1 account` | `Owned` |  | `Tier 2` | Legacy prompt-refinement adapters, BrowserAct workflow hooks, and visual-director provider hints | Wired as a bounded prompt/style helper for internal guide pipelines; still not a general runtime planner dependency. |
| `ChatPlayground AI` | `Unlimited Plan` | `1 account` | `Owned` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `Soundmadeseen` | `API Access` | `1 key` | `Owned` |  | `Tier 4` | `.env` placeholder/secret tracked locally | API key exists in local `.env`; service-level workflow and account-level verification are still pending. |
| `Emailit` | `Tier 5` | `1 account / 1 key` | `Owned` |  | `Tier 4` | Local `.env` API key only | API key is stored locally for transactional email delivery wiring; runtime integration and sender-domain verification are still pending. |
| `AI Magicx` | `Rune Plan` | `1 account` | `Owned` |  | `Tier 1` | `ea/app/services/responses_upstream.py` fallback lane and `ea/app/api/routes/responses.py` `/v1/codex` selectors | Routed as a gated secondary lane for short/overflow paths and audit support where 1min capacity is constrained. |
| `FastestVPN PRO` | `15 Devices` | `1 subscription/account` | `Owned` |  | `Tier 3` | None | Infrastructure/privacy utility, not currently wired into this repo. |
| `OneAir` | `Elite` | `1 account` | `Owned` |  | `Tier 3` | None | Travel utility only; no local runtime integration yet. |
| `Headway` | `Premium` | `1 account` | `Owned` |  | `Tier 3` | None | Knowledge/content utility only; no local runtime integration yet. |
| `VidBoard.ai` | `Tier 5` | `1 account` | `Owned` |  | `Tier 4` | BrowserAct-stored credentials for account access; no active runtime lane yet | Newly tracked LTD; account access exists, but no structured verification run or workspace integration is pinned yet. |
| `hedy.ai` | `LTD account` | `1 account` | `Owned` |  | `Tier 4` | Local `.env` username/password only | Credentials are stored locally for later browser-driven account access or structured verification; no active runtime lane is wired yet. |
| `Internxt Cloud Storage` | `100TB` | `1 account` | `Owned` |  | `Tier 3` | None | Storage service not currently wired into the workspace. |

## AppSumo LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `ApiX-Drive` | `Plus exclusive / License Tier 3` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no active local runtime integration is verified in this repo yet. |
| `ApproveThis` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct content-template packets for approval-queue reading plus skill-catalog references in external-send flows | Ready for BrowserAct-backed queue reading and approval-lane observation without treating ApproveThis as the internal policy engine. |
| `AvoMap` | `10x code-based` | `10 codes` | `Activated` |  | `Tier 2` | BrowserAct video-renderer scaffold packets archived under `/mnt/pcloud/EA` | All codes redeemed and activated; local integration is still staged, not a verified end-to-end production lane. |
| `BrowserAct` | `Tier 3` | `1 product` | `Activated` |  | `Tier 1` | `browseract.extract_account_facts`, `browseract.extract_account_inventory`, `browseract_extract_then_artifact`, local BrowserAct key slots, and connector-bound account-fact discovery | Plan/Tier and activation status are sourced from BrowserAct-backed inventory extraction; run date remains pending external receipt for audit trail. |
| `Crezlo Tours` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 1` | BrowserAct-backed property-tour pipeline, public publishing path, and email delivery scripts | Property ingestion, tour generation, publishing, and delivery are wired in this repo. |
| `Documentation.AI` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no active local runtime integration is verified in this repo yet. |
| `First Book ai` | `License Tier 5` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct-stored credentials for account access; no active runtime lane is verified in this repo yet | Activation is confirmed; browser-driven account access exists, but a production runtime lane is not yet pinned here. |
| `Invoiless` | `1x code-based` | `1 code` | `Activated` |  | `Tier 3` | None | Redeemed and activated; still out of the current hot-path product architecture. |
| `Lunacal` | `Tier 4` | `1 account` | `Activated` |  | `Tier 4` | BrowserAct-stored credentials for account access; no active runtime lane yet | Tier 4 is confirmed at `app.lunacal.ai`, and BrowserAct holds the account credentials for later structured verification. |
| `MarkupGo` | `7x code-based` | `7 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; ready for adapter-first media use when needed. |
| `MetaSurvey` | `Plus exclusive / 3x code-based` | `3 codes` | `Activated` |  | `Tier 2` | BrowserAct content-template packets for survey-results reading | Redeemed and activated; structured feedback collection has staged extraction support, not a verified end-to-end lane. |
| `Mootion` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct video-renderer scaffold packets archived under `/mnt/pcloud/EA` | Activation is confirmed; the current local posture is scaffold-stage workflow generation, not yet a production render lane. |
| `Nonverbia` | `Tier 4` | `1 account` | `Activated` |  | `Tier 2` | BrowserAct-stored credentials for account access; no active runtime lane yet | Official Nonverbia app access is available at `app.nonverbia.com`, and account credentials are stored in BrowserAct for later structured verification. |
| `Paperguide` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no active local runtime integration is verified in this repo yet. |
| `PeekShot` | `3x code-based` | `3 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; suitable for preview/thumbnail adapter work when wired. |
| `Teable` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 2` | Referenced historically as a possible projection surface, not active runtime storage | Keep out of the hot-path runtime database role; use only as a curated projection if revived. |
| `Unmixr AI` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no active local runtime integration is verified in this repo yet. |
| `Vizologi` | `Plus exclusive / 4x code-based` | `4 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; retained for strategy/research support only. |

## Summary

- `30` total LTD products tracked
- Multiple-code holdings: `AvoMap`, `MarkupGo`, `MetaSurvey`, `PeekShot`, `Vizologi`
- Multiple-account holding: `1min.AI` (`12 licenses / 12 accounts`)

## Discovery Tracking

Use this section to track missing tier/email/account facts discovered through the BrowserAct-backed runtime flow.

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `1min.AI` |  | `manual_seeded` | `local_env` |  | API-key rotation slots exist locally; account emails are still not documented here. |
| `Prompting Systems` |  | `missing` | `manual_inventory` |  | Local prompt-refinement wiring exists; account-level verification still has no BrowserAct discovery run recorded yet. |
| `ChatPlayground AI` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Soundmadeseen` |  | `complete` | `local_env` |  | API key captured locally; plan/tier and account email still need discovery. |
| `Emailit` |  | `manual_seeded` | `local_env` |  | Tier 5 is noted manually and the API key is stored locally; account-level verification and sender-domain setup are still pending. |
| `AI Magicx` |  | `missing` | `manual_inventory` |  | Local overflow-response wiring exists; account-level verification still has no BrowserAct discovery run recorded yet. |
| `FastestVPN PRO` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `OneAir` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Headway` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `VidBoard.ai` | `the.girscheles@gmail.com` | `manual_seeded` | `browseract_local` | 2026-04-14T00:00:00Z | Tier 5 and account email were seeded manually; credentials remain out of git and structured BrowserAct verification is still pending. |
| `hedy.ai` | `the.girscheles@gmail.com` | `manual_seeded` | `local_env` | 2026-04-02T00:00:00Z | Username/password are stored locally; plan/tier and activation details still need structured verification. |
| `Internxt Cloud Storage` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `ApiX-Drive` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `ApproveThis` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `AvoMap` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `BrowserAct` | ops@example.com | `complete` | `browseract_live` | 2026-03-07T00:00:00Z | Plan/Tier: Tier 3; Status: activated |
| `Crezlo Tours` |  | `missing` | `manual_inventory` |  | License Tier 4 is confirmed manually and credentials are stored in BrowserAct, but no structured account-detail verification run is recorded yet. |
| `Documentation.AI` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `First Book ai` |  | `missing` | `manual_inventory` |  | License Tier 5 is confirmed manually and credentials are stored in BrowserAct, but no structured account-detail verification run is recorded yet. |
| `Invoiless` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `Lunacal` |  | `partial` | `connector_metadata` | 2026-03-31T19:24:24.399857+00:00 | Plan/Tier: Tier 4; Status: activated; Missing fields: account_email |
| `MarkupGo` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `MetaSurvey` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `Mootion` |  | `complete` | `manual_inventory` |  | Plan/Tier: License Tier 3; Status: activated |
| `Nonverbia` |  | `missing` | `manual_inventory` |  | Tier 4 is confirmed manually and credentials are stored in BrowserAct, but no structured account-detail verification run is recorded yet. |
| `Paperguide` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `PeekShot` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `Teable` | ops@teable.example | `complete` | `browseract_live` | 2026-03-07T00:01:00Z | Plan/Tier: License Tier 4; Status: activated |
| `Unmixr AI` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Vizologi` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |

## Attention Items

None right now. All tracked LTDs are redeemed and activated; remaining follow-up is only account-detail verification and any later runtime wiring.

## Notes

- The Codex session skill list is not the LTD source of truth; skills are local agent capabilities, while this file tracks your external services/accounts.
- Product/deal tier (`License Tier 3`, `Gold Plan`, `Elite`, etc.) is separate from the workspace integration tier used to describe local wiring posture.
- Secrets are intentionally omitted here; only inventory, status, deadlines, and local integration contracts are documented.
- BrowserAct inventory artifacts can refresh the `## Discovery Tracking` table, `Updated:` stamp, and total-count summary through `bash scripts/refresh_ltds_from_inventory.sh --input <inventory.json> --write` when a fresh structured inventory payload is available.
- If the local EA API and BrowserAct binding are already configured, `bash scripts/refresh_ltds_via_api.sh --binding-id <browseract-binding-id> --service-name BrowserAct --service-name Teable --write` can execute the `ltd_inventory_refresh` skill and rewrite this file without manually exporting the intermediate JSON first.
