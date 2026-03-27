from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_browseract_content_templates.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_browseract_content_templates", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BrowserActContentTemplateTests(unittest.TestCase):
    def test_catalog_includes_onemin_daily_bonus_billing_usage_and_members_reconciliation(self) -> None:
        module = _load_module()
        templates = {str(entry["slug"]): entry for entry in module.templates()}

        daily_bonus = templates["onemin_daily_bonus_checkin_live"]
        self.assertEqual(daily_bonus["workflow_kind"], "page_extract")
        self.assertEqual(daily_bonus["login_url"], "https://app.1min.ai/login")
        self.assertEqual(daily_bonus["tool_url"], "https://app.1min.ai/billing-usage")
        self.assertEqual(daily_bonus["result_field_name"], "daily_bonus_page")
        self.assertIn("workflow_spec_json", daily_bonus)
        self.assertEqual(daily_bonus["workflow_spec_json"]["meta"]["workflow_kind"], "page_extract")

        billing_usage = templates["onemin_billing_usage_reader_live"]
        self.assertEqual(billing_usage["workflow_kind"], "page_extract")
        self.assertEqual(billing_usage["login_url"], "https://app.1min.ai/login")
        self.assertEqual(billing_usage["tool_url"], "https://app.1min.ai/billing-usage")
        self.assertEqual(billing_usage["result_field_name"], "billing_usage_bonus_page")
        self.assertTrue(billing_usage["dismiss_selectors"])
        self.assertIn("workflow_spec_json", billing_usage)
        submit_node = next(node for node in billing_usage["workflow_spec_json"]["nodes"] if node["id"] == "submit")
        self.assertEqual(submit_node["type"], "submit_login_form")
        self.assertTrue(any(node["id"] == "unlock_free_credits" for node in billing_usage["workflow_spec_json"]["nodes"]))
        self.assertTrue(any(node["id"] == "extract_pre_bonus_page" for node in billing_usage["workflow_spec_json"]["nodes"]))
        self.assertTrue(any(node["id"] == "extract_billing_bonus_page" for node in billing_usage["workflow_spec_json"]["nodes"]))

        members = templates["onemin_members_reconciliation_live"]
        self.assertEqual(members["workflow_kind"], "page_extract")
        self.assertEqual(members["login_url"], "https://app.1min.ai/login")
        self.assertEqual(members["tool_url"], "https://app.1min.ai/members")
        self.assertEqual(members["result_field_name"], "members_page")
        self.assertTrue(members["dismiss_selectors"])
        self.assertIn("workflow_spec_json", members)
        wait_login_entry = next(node for node in members["workflow_spec_json"]["nodes"] if node["id"] == "wait_login_entry")
        self.assertTrue(wait_login_entry["config"]["optional"])


if __name__ == "__main__":
    unittest.main()
