# LTDs

Consolidated inventory of your lifetime services/products, including product tier/plan, ownership status, redemption deadlines, and local workspace integration posture.

Updated: 2026-03-15

## Workspace Integration Tier Guide

- `Tier 1`: actively wired into the local workspace/runtime and ready for operational use
- `Tier 2`: owned and partially wired, referenced, or intentionally parked in the local workspace
- `Tier 3`: owned and tracked, but no active local workspace integration yet
- `Tier 4`: credential captured in local environment, but no active runtime lane or account verification yet

## Non-AppSumo / Other LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `1min.AI` | `Advanced Business Plan` | `10 licenses / 10 accounts` | `Owned` |  | `Tier 1` | Local `.env` key rotation slots plus `scripts/resolve_onemin_ai_key.sh` | Primary and fallback API-key flow is wired locally and kept out of git. |
| `Prompting Systems` | `Gold Plan` | `1 account` | `Owned` |  | `Tier 2` | Chummer6 guide prompt-refinement adapters, BrowserAct workflow hooks, and visual-director provider hints | Wired as a bounded prompt/style helper for the Chummer6 guide pipeline; still not a general runtime planner dependency. |
| `ChatPlayground AI` | `Unlimited Plan` | `1 account` | `Owned` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `Soundmadeseen` | `API Access` | `1 key` | `Owned` |  | `Tier 4` | `.env` placeholder/secret tracked locally | API key exists in local `.env`; service-level workflow and account-level verification are still pending. |
| `AI Magicx` | `Rune Plan` | `1 account` | `Owned` |  | `Tier 1` | `ea/app/services/responses_upstream.py` fallback lane and `ea/app/api/routes/responses.py` `/v1/codex` selectors | Routed as a gated secondary lane for short/overflow paths and audit support where 1min capacity is constrained. |
| `Browserly` | `Plan pending verification` | `1 account` | `Owned` |  | `Tier 2` | EA provider-registry catalog hint, Browserly env placeholders, and media-factory vendor-map reservation | Tracked as a browser-assisted capture/reference vendor; exact deal tier and account facts still need verification before runtime promotion. |
| `FastestVPN PRO` | `15 Devices` | `1 subscription/account` | `Owned` |  | `Tier 3` | None | Infrastructure/privacy utility, not currently wired into this repo. |
| `OneAir` | `Elite` | `1 account` | `Owned` |  | `Tier 3` | None | Travel utility only; no local runtime integration yet. |
| `Headway` | `Premium` | `1 account` | `Owned` |  | `Tier 3` | None | Knowledge/content utility only; no local runtime integration yet. |
| `Internxt Cloud Storage` | `100TB` | `1 account` | `Owned` |  | `Tier 3` | None | Storage service not currently wired into the workspace. |

## AppSumo LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `ApiX-Drive` | `Plus exclusive / License Tier 3` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `ApproveThis` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct content-template packets for approval-queue reading plus skill-catalog references in external-send flows | Ready for BrowserAct-backed queue reading and approval-lane observation without treating ApproveThis as the internal policy engine. |
| `AvoMap` | `10x code-based` | `10 codes` | `Activated` |  | `Tier 2` | BrowserAct video-renderer scaffold packets archived under `/mnt/pcloud/EA` | All codes redeemed and activated; local integration is still staged, but the workflow-spec skill now emits real renderer scaffolds. |
| `BrowserAct` | `Tier 3` | `1 product` | `Activated` |  | `Tier 1` | `browseract.extract_account_facts`, `browseract.extract_account_inventory`, `browseract_extract_then_artifact`, local BrowserAct key slots, and connector-bound account-fact discovery | Plan/Tier and activation status are sourced from BrowserAct-backed inventory extraction; run date remains pending external receipt for audit trail. |
| `Documentation.AI` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `Invoiless` | `1x code-based` | `1 code` | `Activated` |  | `Tier 3` | None | Redeemed and activated; still out of the current hot-path product architecture. |
| `MarkupGo` | `7x code-based` | `7 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; ready for adapter-first media use when needed. |
| `MetaSurvey` | `Plus exclusive / 3x code-based` | `3 codes` | `Activated` |  | `Tier 2` | BrowserAct content-template packets for survey-results reading | Redeemed and activated; structured feedback collection now has a staged BrowserAct extraction template instead of only a wishlist note. |
| `Mootion` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 2` | BrowserAct video-renderer scaffold packets archived under `/mnt/pcloud/EA` | Activation is confirmed; the current local posture is scaffold-stage workflow generation, not yet a production render lane. |
| `Paperguide` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `PeekShot` | `3x code-based` | `3 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; suitable for preview/thumbnail adapter work when wired. |
| `Teable` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 2` | Referenced historically as a possible projection surface, not active runtime storage | Keep out of the hot-path runtime database role; use only as a curated projection if revived. |
| `Unmixr AI` | `License Tier 4` | `1 license` | `Activated` |  | `Tier 3` | None | Tracked LTD only; no local runtime integration yet. |
| `Vizologi` | `Plus exclusive / 4x code-based` | `4 codes` | `Activated` |  | `Tier 3` | None | Redeemed and activated; retained for strategy/research support only. |

## Summary

- `24` total LTD products tracked
- Multiple-code holdings: `AvoMap`, `MarkupGo`, `MetaSurvey`, `PeekShot`, `Vizologi`
- Multiple-account holding: `1min.AI` (`10 licenses / 10 accounts`)

## Discovery Tracking

Use this section to track missing tier/email/account facts discovered through the BrowserAct-backed runtime flow.

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `1min.AI` |  | `manual_seeded` | `local_env` |  | API-key rotation slots exist locally; account emails are still not documented here. |
| `Prompting Systems` |  | `missing` | `manual_inventory` |  | Local Chummer6 prompt-refinement wiring exists; account-level verification still has no BrowserAct discovery run recorded yet. |
| `ChatPlayground AI` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Soundmadeseen` |  | `complete` | `local_env` |  | API key captured locally; plan/tier and account email still need discovery. |
| `AI Magicx` |  | `missing` | `manual_inventory` |  | Local Chummer6 render wiring exists; account-level verification still has no BrowserAct discovery run recorded yet. |
| `Browserly` |  | `missing` | `manual_inventory` |  | Deal/account facts still need verification; Browserly is reserved as a browser-assisted capture/reference vendor. |
| `FastestVPN PRO` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `OneAir` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Headway` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Internxt Cloud Storage` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `ApiX-Drive` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `ApproveThis` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `AvoMap` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `BrowserAct` | ops@example.com | `complete` | `browseract_live` | 2026-03-07T00:00:00Z | Plan/Tier: Tier 3; Status: activated |
| `Documentation.AI` |  | `missing` | `manual_inventory` |  | No BrowserAct discovery run recorded yet. |
| `Invoiless` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `MarkupGo` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `MetaSurvey` |  | `missing` | `manual_inventory` |  | Activated; account-level verification details are still not documented here. |
| `Mootion` |  | `complete` | `manual_inventory` |  | Plan/Tier: License Tier 3; Status: activated |
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
- BrowserAct inventory artifacts can refresh the `## Discovery Tracking` table through `bash scripts/refresh_ltds_from_inventory.sh --input <inventory.json> --write` when a fresh structured inventory payload is available.
- If the local EA API and BrowserAct binding are already configured, `bash scripts/refresh_ltds_via_api.sh --binding-id <browseract-binding-id> --service-name BrowserAct --service-name Teable --write` can execute the `ltd_inventory_refresh` skill and rewrite this file without manually exporting the intermediate JSON first.
