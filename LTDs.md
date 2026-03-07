# LTDs

Consolidated inventory of your lifetime services/products, including product tier/plan, ownership status, redemption deadlines, and local workspace integration posture.

Updated: 2026-03-07

## Workspace Integration Tier Guide

- `Tier 1`: actively wired into the local workspace/runtime and ready for operational use
- `Tier 2`: owned and partially wired, referenced, or intentionally parked in the local workspace
- `Tier 3`: owned and tracked, but no active local workspace integration yet

## Non-AppSumo / Other LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `1min.AI` | `Advanced Business Plan` | `2 licenses / 2 accounts` | `Owned` |  | `Tier 1` | Local `.env` key rotation slots plus `scripts/resolve_onemin_ai_key.sh` | Primary and fallback API-key flow is wired locally and kept out of git. |
| `Prompting Systems` | `Gold Plan` | `1 account` | `Owned` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `ChatPlayground AI` | `Unlimited Plan` | `1 account` | `Owned` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `AI Magicx` | `Rune Plan` | `1 account` | `Owned` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `FastestVPN PRO` | `15 Devices` | `1 subscription/account` | `Owned` |  | `Tier 3` | None | Infrastructure/privacy utility, not currently wired into this repo. |
| `OneAir` | `Elite` | `1 account` | `Owned` |  | `Tier 3` | None | Travel utility only; no local runtime integration yet. |
| `Headway` | `Premium` | `1 account` | `Owned` |  | `Tier 3` | None | Knowledge/content utility only; no local runtime integration yet. |
| `Internxt Cloud Storage` | `100TB` | `1 account` | `Owned` |  | `Tier 3` | None | Storage service not currently wired into the workspace. |

## AppSumo LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `ApiX-Drive` | `Plus exclusive / License Tier 3` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `ApproveThis` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `AvoMap` | `10x code-based` | `10 codes` | `9 redeemed / 1 pending` | `2026-05-02` | `Tier 3` | None | One remaining code must be redeemed by May 2, 2026. |
| `BrowserAct` | `Tier unspecified` | `1 product` | `Unknown` |  | `Tier 1` | `browseract.extract_account_facts`, `browseract.extract_account_inventory`, `browseract_extract_then_artifact`, local BrowserAct key slots, and connector-bound account-fact discovery | Tier, activation status, and purchase date still unclear; runtime discovery is now wired for both single-service facts and multi-service LTD inventory refresh, but live verification still needs a configured BrowserAct run target. |
| `Documentation.AI` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `Invoiless` | `1x code-based` | `1 code` | `Pending redemption` | `2026-04-29` | `Tier 3` | None | Redeem by April 29, 2026. |
| `MarkupGo` | `7x code-based` | `7 codes` | `Pending redemption` | `2026-04-28` | `Tier 3` | None | Redeem by April 28, 2026. |
| `MetaSurvey` | `Plus exclusive / 3x code-based` | `3 codes` | `Pending redemption` | `2026-04-29` | `Tier 3` | None | Redeem by April 29, 2026. |
| `Paperguide` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `PeekShot` | `3x code-based` | `3 codes` | `Pending redemption` | `2026-04-30` | `Tier 3` | None | Redeem by April 30, 2026. |
| `Teable` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 2` | Referenced historically as a possible projection surface, not active runtime storage | Keep out of the hot-path runtime database role; use only as a curated projection if revived. |
| `Vizologi` | `Plus exclusive / 4x code-based` | `4 codes` | `Pending redemption` | `2026-04-30` | `Tier 3` | None | Redeem by April 30, 2026. |

## Summary

- `20` total LTD products tracked
- Multiple-code holdings: `AvoMap`, `MarkupGo`, `MetaSurvey`, `PeekShot`, `Vizologi`
- Multiple-account holding: `1min.AI` (`2 licenses / 2 accounts`)

## Discovery Tracking

Use this section to track missing tier/email/account facts discovered through the BrowserAct-backed runtime flow.

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `1min.AI` |  | `manual_seeded` | `local_env` |  | API-key rotation slots exist locally; account emails are still not documented here. |
| `Prompting Systems` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `ChatPlayground AI` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `AI Magicx` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `FastestVPN PRO` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `OneAir` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Headway` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Internxt Cloud Storage` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `ApiX-Drive` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `ApproveThis` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `AvoMap` |  | `missing` | `manual_inventory` |  | Remaining redemption work still blocks final account verification. |
| `BrowserAct` |  | `runtime_ready` | `browseract.extract_account_inventory` |  | The EA runtime can now resolve tier/email/status facts from a BrowserAct connector binding for one service or a whole LTD inventory slice and persist those results as structured artifacts; live values are still pending. |
| `Documentation.AI` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Invoiless` |  | `missing` | `manual_inventory` |  | Pending redemption before account verification. |
| `MarkupGo` |  | `missing` | `manual_inventory` |  | Pending redemption before account verification. |
| `MetaSurvey` |  | `missing` | `manual_inventory` |  | Pending redemption before account verification. |
| `Paperguide` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `PeekShot` |  | `missing` | `manual_inventory` |  | Pending redemption before account verification. |
| `Teable` |  | `missing` | `manual_inventory` |  | Workspace references exist, but no account-fact discovery run is documented here yet. |
| `Vizologi` |  | `missing` | `manual_inventory` |  | Pending redemption before account verification. |

## Attention Items

| Service | Action Needed | Deadline |
|---|---|---|
| `MarkupGo` | Redeem pending codes | `2026-04-28` |
| `Invoiless` | Redeem pending code | `2026-04-29` |
| `MetaSurvey` | Redeem pending codes | `2026-04-29` |
| `PeekShot` | Redeem pending codes | `2026-04-30` |
| `Vizologi` | Redeem pending codes | `2026-04-30` |
| `AvoMap` | Redeem 1 remaining code | `2026-05-02` |
| `BrowserAct` | Confirm tier and activation details |  |

## Notes

- The Codex session skill list is not the LTD source of truth; skills are local agent capabilities, while this file tracks your external services/accounts.
- Product/deal tier (`License Tier 3`, `Gold Plan`, `Elite`, etc.) is separate from the workspace integration tier used to describe local wiring posture.
- Secrets are intentionally omitted here; only inventory, status, deadlines, and local integration contracts are documented.
- BrowserAct inventory artifacts can refresh the `## Discovery Tracking` table through `bash scripts/refresh_ltds_from_inventory.sh --input <inventory.json> --write` when a fresh structured inventory payload is available.
