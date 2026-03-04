# Newspaper Feature Matrix (Design -> Evidence -> Status)

Date: 2026-03-03

## Layout & Editorial

| Requirement | Evidence | Status |
|---|---|---|
| Multi-page newspaper issue (not single-page dump) | `tests/check_newspaper_pdf.py` enforces `page_count >= 2` | Guard added |
| Visual-first output (images per issue/stories) | `tests/check_newspaper_pdf.py` requires embedded images; `tests/smoke_issue_visual_coverage.py` requires per-story visual fallback | Guard added |
| No raw debug/error leakage in published artifact | `tests/check_newspaper_pdf.py` bans debug tokens | Guard added |
| No raw debug/error leakage in Telegram messages | `tests/smoke_telegram_payload_sanitized.py` bans leakage tokens | Guard added |

## Pipeline Reliability

| Requirement | Evidence | Status |
|---|---|---|
| Host remains responsive during heavy job | `scripts/smoke_host_survivability.sh` with cgroup caps and OOM checks | Test added |
| Browser/render concurrency bounded | `scripts/smoke_browser_concurrency.sh` with `MAX_BROWSERS` threshold | Test added |
| Temporary-file growth bounded | `scripts/smoke_tmp_growth.sh` with `MAX_TMP_DELTA_MB` threshold | Test added |

## Runtime Compliance Fixes (already patched)

| Requirement | Evidence | Status |
|---|---|---|
| API role serves full app routes | `ea/app/runner.py` uses `uvicorn.run(\"app.main:app\", ...)` | Fixed |
| Webhook ingress auth boundary | `ea/app/main.py` `_require_ingest_auth` for ApiXDrive/MetaSurvey/BrowserAct | Fixed |
| External event pipeline idempotent and schema-aligned | `ea/app/workers/event_worker.py`, `ea/app/intake/browseract.py`, `ea/app/approvals/normalizer.py` switched to `external_events.id` | Fixed |
| Missing runtime tables provisioned | `ea/app/db.py` and `ea/schema/20260303_v1_18_1_runtime_alignment.sql` | Fixed |
| `/vrief:` command works as `/brief` | `ea/app/poll_listener.py` alias mapping + command normalization | Fixed |

## Remaining Manual Validation

| Requirement | Evidence Needed | Status |
|---|---|---|
| Human design quality (masthead/columns/section spread aesthetics) | Visual QA on generated newspaper PDF | Pending manual review |
| Per-tenant editorial relevance and ranking quality | Tenant-by-tenant output sampling | Pending manual review |
