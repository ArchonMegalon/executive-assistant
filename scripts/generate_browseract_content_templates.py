#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_OUTPUT_DIR = Path("/mnt/pcloud/EA/browseract_templates")
ONEMIN_LOGIN_URL = "https://app.1min.ai/login"
ONEMIN_APP_URL = "https://app.1min.ai/"
ONEMIN_BILLING_USAGE_URL = "https://app.1min.ai/billing-usage"
COMMON_CLOSE_SELECTORS = [
    "button[aria-label='Close']",
    "button[title='Close']",
    "[data-testid='close']",
]


def build_skill_payload() -> dict[str, object]:
    return {
        "skill_key": "browseract_bootstrap_manager",
        "task_key": "browseract_bootstrap_manager",
        "name": "BrowserAct Bootstrap Manager",
        "description": "Planner-executed BrowserAct workflow-spec builder for stage-0 BrowserAct template creation and architect packets.",
        "deliverable_type": "browseract_workflow_spec_packet",
        "default_risk_class": "medium",
        "default_approval_class": "none",
        "workflow_template": "tool_then_artifact",
        "allowed_tools": ["browseract.build_workflow_spec", "artifact_repository"],
        "evidence_requirements": ["target_domain_brief", "workflow_spec", "browseract_seed_state"],
        "memory_write_policy": "none",
        "memory_reads": ["entities", "relationships"],
        "memory_writes": [],
        "tags": ["browseract", "bootstrap", "workflow", "architect"],
        "authority_profile_json": {"authority_class": "draft", "review_class": "operator"},
        "provider_hints_json": {"primary": ["BrowserAct"]},
        "tool_policy_json": {"allowed_tools": ["browseract.build_workflow_spec", "artifact_repository"]},
        "human_policy_json": {"review_roles": ["automation_architect"]},
        "evaluation_cases_json": [{"case_key": "browseract_bootstrap_manager_golden", "priority": "medium"}],
        "budget_policy_json": {
            "class": "medium",
            "workflow_template": "tool_then_artifact",
            "pre_artifact_capability_key": "workflow_spec_build",
            "browseract_failure_strategy": "retry",
            "browseract_max_attempts": 2,
            "browseract_retry_backoff_seconds": 1,
        },
    }


def templates() -> list[dict[str, object]]:
    return [
        {
            "slug": "onemin_daily_bonus_checkin_live",
            "workflow_name": "1min Daily Bonus Check-in",
            "purpose": "Sign in to the 1min.AI app, land on the authenticated home/dashboard surface, and extract the visible daily bonus or check-in state so operators can verify the daily credit claim path.",
            "login_url": ONEMIN_LOGIN_URL,
            "tool_url": ONEMIN_APP_URL,
            "workflow_kind": "page_extract",
            "wait_selector": "main, body",
            "title_selector": "h1, h2, [role='heading']",
            "result_selector": "main, body",
            "result_field_name": "daily_bonus_page",
            "dismiss_selectors": COMMON_CLOSE_SELECTORS,
        },
        {
            "slug": "onemin_billing_usage_reader_live",
            "workflow_name": "1min Billing Usage Reader",
            "purpose": "Sign in to the 1min.AI app, open the billing/usage surface, and extract the visible credits, renewal, and usage text for later normalization into billing snapshots.",
            "login_url": ONEMIN_LOGIN_URL,
            "tool_url": ONEMIN_BILLING_USAGE_URL,
            "workflow_kind": "page_extract",
            "wait_selector": "main, body",
            "title_selector": "h1, h2, [role='heading']",
            "result_selector": "main, body",
            "result_field_name": "billing_usage_page",
            "dismiss_selectors": COMMON_CLOSE_SELECTORS,
        },
        {
            "slug": "economist_article_reader_live",
            "workflow_name": "Economist Article Reader",
            "purpose": "Open a logged-in Economist article URL, dismiss overlays, and extract the readable title and article body.",
            "login_url": "https://www.economist.com/login",
            "tool_url": "https://www.economist.com",
            "workflow_kind": "page_extract",
            "runtime_input_name": "article_url",
            "wait_selector": "article",
            "title_selector": "article h1, h1[data-test-id='ArticleHeadline']",
            "result_selector": "article",
            "dismiss_selectors": ["button[aria-label='Close']", "button[data-testid='closeButton']"],
        },
        {
            "slug": "atlantic_article_reader_live",
            "workflow_name": "Atlantic Article Reader",
            "purpose": "Open a logged-in Atlantic article URL, dismiss overlays, and extract the readable headline and story body.",
            "login_url": "https://accounts.theatlantic.com/login",
            "tool_url": "https://www.theatlantic.com",
            "workflow_kind": "page_extract",
            "runtime_input_name": "article_url",
            "wait_selector": "article",
            "title_selector": "article h1, main h1",
            "result_selector": "article, main article, .article-body",
            "dismiss_selectors": ["button[aria-label='Close']", "button[title='Close']"],
        },
        {
            "slug": "nytimes_article_reader_live",
            "workflow_name": "NYTimes Article Reader",
            "purpose": "Open a logged-in New York Times article URL, dismiss overlays, and extract the readable headline and body.",
            "login_url": "https://myaccount.nytimes.com/auth/login",
            "tool_url": "https://www.nytimes.com",
            "workflow_kind": "page_extract",
            "runtime_input_name": "article_url",
            "wait_selector": "article",
            "title_selector": "article h1, header h1",
            "result_selector": "article, section[name='articleBody']",
            "dismiss_selectors": ["button[aria-label='Close']", "button[data-testid='GDPR-close']"],
        },
        {
            "slug": "approvethis_queue_reader_live",
            "workflow_name": "ApproveThis Queue Reader",
            "purpose": "Open the logged-in ApproveThis queue/dashboard and extract the pending approvals view without relying on manual clicks.",
            "login_url": "https://app.approvethis.com/login",
            "tool_url": "https://app.approvethis.com",
            "workflow_kind": "page_extract",
            "wait_selector": "main, table, [data-testid='approvals-list']",
            "title_selector": "h1, h2",
            "result_selector": "main",
            "dismiss_selectors": ["button[aria-label='Close']", "button[title='Close']"],
        },
        {
            "slug": "metasurvey_results_reader_live",
            "workflow_name": "MetaSurvey Results Reader",
            "purpose": "Open a logged-in MetaSurvey survey or results page, dismiss overlays, and extract the visible survey summary/results content.",
            "login_url": "https://getmetasurvey.com/login",
            "tool_url": "https://getmetasurvey.com",
            "workflow_kind": "page_extract",
            "runtime_input_name": "survey_url",
            "wait_selector": "main, article, [data-testid='survey-results']",
            "title_selector": "h1, h2",
            "result_selector": "main",
            "dismiss_selectors": ["button[aria-label='Close']", "button[title='Close']"],
        },
    ]


def client():
    from fastapi.testclient import TestClient

    os.environ.setdefault("EA_STORAGE_BACKEND", "memory")
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.setdefault("EA_API_TOKEN", "")
    from app.api.app import create_app

    test_client = TestClient(create_app())
    test_client.headers.update({"X-EA-Principal-ID": "exec-1"})
    return test_client


def main() -> int:
    output_dir = Path(os.environ.get("EA_BROWSERACT_TEMPLATE_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    api = client()
    response = api.post("/v1/skills", json=build_skill_payload())
    response.raise_for_status()

    summary: list[dict[str, object]] = []
    for template in templates():
        execute = api.post(
            "/v1/plans/execute",
            json={
                "skill_key": "browseract_bootstrap_manager",
                "goal": f"build the {template['workflow_name']} workflow spec packet",
                "input_json": {k: v for k, v in template.items() if k != "slug"},
            },
        )
        execute.raise_for_status()
        body = execute.json()
        slug = str(template["slug"])
        structured_output = dict(body["structured_output_json"] or {})
        packet_path = output_dir / f"{slug}.packet.json"
        workflow_path = output_dir / f"{slug}.workflow.json"
        payload_text = json.dumps(structured_output, indent=2) + "\n"
        packet_path.write_text(payload_text, encoding="utf-8")
        workflow_path.write_text(payload_text, encoding="utf-8")
        summary.append(
            {
                "slug": slug,
                "workflow_name": structured_output.get("workflow_name"),
                "path": str(packet_path),
                "workflow_path": str(workflow_path),
                "kind": body.get("kind"),
            }
        )

    summary_path = output_dir / "browseract_content_templates.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output_dir": str(output_dir), "count": len(summary)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
