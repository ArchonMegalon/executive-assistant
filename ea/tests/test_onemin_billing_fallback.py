from __future__ import annotations

from app.services.browseract_ui_template_catalog import browseract_ui_template_spec
from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter


def test_onemin_billing_workflow_captures_home_after_login_before_billing_route() -> None:
    spec = browseract_ui_template_spec("onemin_billing_usage_reader_live")
    node_ids = [str(node.get("id") or "") for node in list(spec.get("nodes") or []) if isinstance(node, dict)]
    edges = {tuple(edge) for edge in list(spec.get("edges") or []) if isinstance(edge, list) and len(edge) == 2}

    assert "wait_authenticated" in node_ids
    assert "extract_home_after_login" in node_ids
    assert "open_billing_usage" in node_ids
    assert node_ids.index("extract_home_after_login") < node_ids.index("open_billing_usage")
    assert ("wait_authenticated", "extract_home_after_login") in edges
    assert ("extract_home_after_login", "open_billing_usage") in edges


def test_normalize_onemin_billing_payload_uses_home_credit_badge_fallback() -> None:
    response = {
        "structured_output_json": {
            "extracts": {
                "home_after_login": (
                    "T\n"
                    "Tibor Girschele\n\n"
                    "Team\n\n"
                    "1min.AI\n"
                    "90,279\n"
                    "Magic Notebook\n"
                    "AI DISCOVERY\n"
                ),
                "billing_settings_page": "Sample Team\nHome\nWorkspace\nAI Studio\n",
            }
        }
    }

    normalized = BrowserActToolAdapter._normalize_onemin_billing_payload(
        response=response,
        source_url="https://app.1min.ai/billing-usage",
        account_label="ONEMIN_AI_API_KEY",
    )

    assert normalized["remaining_credits"] == 90279
    assert normalized["basis"] == "actual_home_credit_badge"
    assert normalized["structured_output_json"]["home_credit_badge_json"] == {
        "present": True,
        "remaining_credits": 90279,
        "basis": "logged_in_home_badge",
    }
