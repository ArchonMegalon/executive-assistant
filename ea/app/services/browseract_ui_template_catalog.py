from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserActUiTemplateDefinition:
    template_key: str
    workflow_name: str
    description: str
    login_url: str
    tool_url: str
    workflow_kind: str
    auth_flow: str = "direct"
    google_entry_selector: str = ""
    google_auth_url: str = ""
    runtime_input_name: str = ""
    authorized_credential_queries: tuple[str, ...] = ()
    direct_pre_auth_dismiss_selectors: tuple[str, ...] = ()
    direct_login_entry_selector: str = ""
    direct_login_entry_dom_click: bool = False
    direct_email_selector: str = "input[type=email], input[name=email], input[name=identifier], input[autocomplete='email'], input[autocomplete='username'], input[type=text][name=email], input[type=text][placeholder*='mail' i]"
    direct_password_selector: str = "input[type=password], input[name=password], input[name=Passwd], input[autocomplete='current-password'], input[placeholder*='Password' i]"
    direct_submit_selector: str = (
        "form button[type=submit], form input[type=submit], button:has-text(\"Sign In\"), "
        "button:has-text(\"Log In\"), button:has-text(\"Login\"), button:has-text(\"Continue\"), button:has-text(\"LOG IN\")"
    )
    prompt_selector: str = "textarea, [contenteditable='true'], input[type='text']"
    submit_selector: str = (
        "button[type=submit], button:has-text(\"Generate\"), button:has-text(\"Create\"), "
        "button:has-text(\"Run\"), button:has-text(\"Continue\")"
    )
    result_selector: str = "main, [role='main'], body"
    wait_selector: str = "main, [role='main'], body"
    title_selector: str = "h1, h2"
    result_field_name: str = "page_body"
    include_dismiss_nodes: bool = False
    dismiss_selectors: tuple[str, ...] = (
        "button[aria-label='Close']",
        "button[title='Close']",
        "[data-testid='close']",
    )

    def _direct_auth_nodes(self) -> tuple[list[dict[str, object]], list[list[str]], str]:
        nodes: list[dict[str, object]] = []
        edges: list[list[str]] = []
        previous = "open_login"
        for index, selector in enumerate(self.direct_pre_auth_dismiss_selectors, start=1):
            wait_id = f"wait_pre_auth_dismiss_{index:02d}"
            click_id = f"pre_auth_dismiss_{index:02d}"
            nodes.extend(
                [
                    {
                        "id": wait_id,
                        "type": "wait",
                        "label": f"Wait Pre-Auth Dismiss {index}",
                        "config": {
                            "selector": selector,
                            "timeout_ms": 2500,
                            "optional": True,
                        },
                    },
                    {
                        "id": click_id,
                        "type": "click",
                        "label": f"Pre-Auth Dismiss {index}",
                        "config": {"selector": selector, "optional": True},
                    },
                ]
            )
            edges.extend([[previous, wait_id], [wait_id, click_id]])
            previous = click_id
        if self.direct_login_entry_selector:
            nodes.extend(
                [
                    {
                        "id": "wait_login_entry",
                        "type": "wait",
                        "label": "Wait Login Entry",
                        "config": {
                            "selector": self.direct_login_entry_selector,
                            "timeout_ms": 45000,
                        },
                    },
                    {
                        "id": "open_login_entry",
                        "type": "click",
                        "label": "Open Login Entry",
                        "config": {
                            "selector": self.direct_login_entry_selector,
                            **({"dom_click": True} if self.direct_login_entry_dom_click else {}),
                            **({"post_click_wait_ms": 1200} if self.direct_login_entry_dom_click else {}),
                        },
                    },
                ]
            )
            edges.extend([[previous, "wait_login_entry"], ["wait_login_entry", "open_login_entry"]])
            previous = "open_login_entry"
        nodes.extend([
            {
                "id": "wait_login_form",
                "type": "wait",
                "label": "Wait Login Form",
                "config": {
                    "selector": self.direct_email_selector,
                    "timeout_ms": 45000,
                },
            },
            {
                "id": "email",
                "type": "input_text",
                "label": "Email",
                "config": {
                    "selector": self.direct_email_selector,
                    "value_from_secret": "browseract_username",
                },
            },
            {
                "id": "password",
                "type": "input_text",
                "label": "Password",
                "config": {
                    "selector": self.direct_password_selector,
                    "value_from_secret": "browseract_password",
                },
            },
            {
                "id": "submit",
                "type": "submit_login_form",
                "label": "Submit Login",
                "config": {
                    "selector": self.direct_submit_selector,
                    "password_selector": self.direct_password_selector,
                },
            },
            {
                "id": "wait_authenticated",
                "type": "wait",
                "label": "Wait Authenticated",
                "config": {
                    "selector": self.direct_password_selector,
                    "state": "hidden",
                    "timeout_ms": 45000,
                },
            },
        ])
        edges.extend([
            [previous, "wait_login_form"],
            ["wait_login_form", "email"],
            ["email", "password"],
            ["password", "submit"],
            ["submit", "wait_authenticated"],
        ])
        return nodes, edges, "wait_authenticated"

    def _google_auth_nodes(self) -> tuple[list[dict[str, object]], list[list[str]], str]:
        nodes: list[dict[str, object]] = []
        edges: list[list[str]] = []
        previous = "open_login"
        if self.google_entry_selector:
            nodes.append(
                {
                    "id": "wait_google_entry",
                    "type": "wait",
                    "label": "Wait Google Entry",
                    "config": {
                        "selector": self.google_entry_selector,
                        "timeout_ms": 45000,
                    },
                }
            )
            nodes.append(
                {
                    "id": "enter_google",
                    "type": "click",
                    "label": "Enter Google Sign-In",
                    "config": {
                        "selector": self.google_entry_selector,
                    },
                }
            )
            edges.append(["open_login", "wait_google_entry"])
            edges.append(["wait_google_entry", "enter_google"])
            previous = "enter_google"
        nodes.extend(
            [
                {
                    "id": "wait_google_email",
                    "type": "wait",
                    "label": "Wait Google Email",
                    "config": {
                        "selector": "input[type=email], input[name=identifier], input[autocomplete='username']",
                        "timeout_ms": 45000,
                    },
                },
                {
                    "id": "google_email",
                    "type": "input_text",
                    "label": "Google Email",
                    "config": {
                        "selector": "input[type=email], input[name=identifier], input[autocomplete='username']",
                        "value_from_secret": "browseract_username",
                    },
                },
                {
                    "id": "google_email_next",
                    "type": "click",
                    "label": "Google Email Next",
                    "config": {
                        "selector": "#identifierNext button, button:has-text(\"Next\"), [role='button']:has-text(\"Next\")",
                    },
                },
                {
                    "id": "wait_google_password",
                    "type": "wait",
                    "label": "Wait Google Password",
                    "config": {
                        "selector": "input[type=password], input[name=Passwd], input[autocomplete='current-password']",
                        "timeout_ms": 45000,
                    },
                },
                {
                    "id": "google_password",
                    "type": "input_text",
                    "label": "Google Password",
                    "config": {
                        "selector": "input[type=password], input[name=Passwd], input[autocomplete='current-password']",
                        "value_from_secret": "browseract_password",
                    },
                },
                {
                    "id": "google_password_next",
                    "type": "click",
                    "label": "Google Password Next",
                    "config": {
                        "selector": "#passwordNext button, button:has-text(\"Next\"), [role='button']:has-text(\"Next\")",
                    },
                },
            ]
        )
        edges.extend(
            [
                [previous, "wait_google_email"],
                ["wait_google_email", "google_email"],
                ["google_email", "google_email_next"],
                ["google_email_next", "wait_google_password"],
                ["wait_google_password", "google_password"],
                ["google_password", "google_password_next"],
            ]
        )
        return nodes, edges, "google_password_next"

    def workflow_spec(self, *, output_dir: str = "/docker/fleet/state/browseract_bootstrap") -> dict[str, object]:
        slug = str(self.template_key or self.workflow_name).strip().lower().replace(" ", "_")
        nodes: list[dict[str, object]] = []
        edges: list[list[str]] = []
        inputs: list[dict[str, str]] = []
        if self.login_url.lower() not in {"", "none", "public", "noauth"}:
            login_target = self.google_auth_url if self.auth_flow == "google_oauth" and self.google_auth_url else self.login_url
            nodes.append(
                {
                    "id": "open_login",
                    "type": "visit_page",
                    "label": "Open Login",
                    "config": {"url": login_target},
                }
            )
            if self.auth_flow == "google_oauth":
                auth_nodes, auth_edges, last_login_node = self._google_auth_nodes()
            else:
                auth_nodes, auth_edges, last_login_node = self._direct_auth_nodes()
            nodes.extend(auth_nodes)
            edges.extend(auth_edges)
        if self.workflow_kind == "prompt_tool":
            inputs.append(
                {
                    "name": "prompt",
                    "description": f"Primary runtime prompt for {self.workflow_name}.",
                }
            )
            nodes.extend(
                [
                    {
                        "id": "open_tool",
                        "type": "visit_page",
                        "label": "Open Tool",
                        "config": {"url": self.tool_url},
                    },
                    {
                        "id": "input_prompt",
                        "type": "input_text",
                        "label": "Input Prompt",
                        "config": {
                            "selector": self.prompt_selector,
                            "value_from_input": "prompt",
                        },
                    },
                    {
                        "id": "submit_prompt",
                        "type": "click",
                        "label": "Submit Prompt",
                        "config": {"selector": self.submit_selector},
                    },
                    {
                        "id": "wait_result",
                        "type": "wait",
                        "label": "Wait Result",
                        "config": {"selector": self.wait_selector, "timeout_ms": 60000},
                    },
                    {
                        "id": "extract_result",
                        "type": "extract",
                        "label": "Extract Result",
                        "config": {
                            "selector": self.result_selector,
                            "field_name": self.result_field_name,
                            "mode": "text",
                        },
                    },
                    {
                        "id": "output_result",
                        "type": "output",
                        "label": "Output Result",
                        "config": {"field_name": self.result_field_name},
                    },
                ]
            )
            edges.extend(
                [
                    ["open_tool", "input_prompt"],
                    ["input_prompt", "submit_prompt"],
                    ["submit_prompt", "wait_result"],
                    ["wait_result", "extract_result"],
                    ["extract_result", "output_result"],
                ]
            )
        else:
            visit_config: dict[str, object] = {}
            if self.runtime_input_name and self.tool_url:
                inputs.append(
                    {
                        "name": self.runtime_input_name,
                        "description": f"Optional target page URL for {self.workflow_name}.",
                    }
                )
            if self.tool_url:
                visit_config["url"] = self.tool_url
                if self.runtime_input_name:
                    visit_config["value_from_input"] = self.runtime_input_name
            last_node = last_login_node if self.login_url.lower() not in {"", "none", "public", "noauth"} else ""
            if visit_config:
                nodes.append(
                    {
                        "id": "open_tool",
                        "type": "visit_page",
                        "label": "Open Target Page",
                        "config": visit_config,
                    }
                )
                if last_node:
                    edges.append([last_node, "open_tool"])
                last_node = "open_tool"
            if self.include_dismiss_nodes:
                for index, selector in enumerate(self.dismiss_selectors, start=1):
                    node_id = f"dismiss_{index:02d}"
                    nodes.append(
                        {
                            "id": node_id,
                            "type": "click",
                            "label": f"Dismiss Overlay {index}",
                            "config": {"selector": selector, "optional": True},
                        }
                    )
                    if last_node:
                        edges.append([last_node, node_id])
                    last_node = node_id
            nodes.append(
                {
                    "id": "wait_content",
                    "type": "wait",
                    "label": "Wait Content",
                    "config": {"selector": self.wait_selector, "timeout_ms": 45000},
                }
            )
            edges.append([last_node, "wait_content"])
            last_node = "wait_content"
            if self.title_selector:
                nodes.append(
                    {
                        "id": "extract_title",
                        "type": "extract",
                        "label": "Extract Title",
                        "config": {"selector": self.title_selector, "field_name": "page_title", "mode": "text"},
                    }
                )
                edges.append([last_node, "extract_title"])
                last_node = "extract_title"
            nodes.append(
                {
                    "id": "extract_result",
                    "type": "extract",
                    "label": "Extract Result",
                    "config": {
                        "selector": self.result_selector,
                        "field_name": self.result_field_name,
                        "mode": "text",
                    },
                }
            )
            nodes.append(
                {
                    "id": "output_result",
                    "type": "output",
                    "label": "Output Result",
                    "config": {"field_name": self.result_field_name},
                }
            )
            edges.extend(
                [
                    [last_node, "extract_result"],
                    ["extract_result", "output_result"],
                ]
            )
        return {
            "workflow_name": self.workflow_name,
            "description": self.description,
            "publish": True,
            "mcp_ready": False,
            "inputs": inputs,
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "slug": self.template_key,
                "output_dir": output_dir,
                "status": "pending_browseract_seed",
                "workflow_kind": self.workflow_kind,
                "auth_flow": self.auth_flow,
                "runtime_input_name": self.runtime_input_name,
                "tool_url": self.tool_url,
                "authorized_credential_queries": list(self.authorized_credential_queries),
            },
        }


_ONEMIN_LOGIN_URL = "https://app.1min.ai/login"
_ONEMIN_BILLING_USAGE_URL = "https://app.1min.ai/billing-usage"
_ONEMIN_MEMBERS_URL = "https://app.1min.ai/members"
_ONEMIN_AUTHORIZED_CREDENTIAL_QUERIES = ("1min.ai", "app.1min.ai")
_ONEMIN_CLOSE_SELECTORS = (
    "[aria-label='Close']",
    ".ant-tour-close",
    "button[title='Close']",
    "[data-testid='close']",
)
_ONEMIN_LOGIN_ENTRY_SELECTOR = "button:has-text(\"Log In\"), a:has-text(\"Log In\"), [role='button']:has-text(\"Log In\")"
_ONEMIN_EMAIL_SELECTOR = "#login_email, input#login_email, input[placeholder='Email'], input[type=email], input[name=email]"
_ONEMIN_PASSWORD_SELECTOR = "#login_password, input#login_password, input[type=password], input[name=password], input[placeholder*='Password' i]"
_ONEMIN_SUBMIT_SELECTOR = (
    ".ant-modal button.ant-btn-primary:has-text(\"Log In\"), "
    ".ant-modal-root button.ant-btn-primary:has-text(\"Log In\"), "
    ".ant-modal-wrap button.ant-btn-primary:has-text(\"Log In\"), "
    ".ant-modal button[type=submit], .ant-modal-root button[type=submit]"
)


def _onemin_meta(*, slug: str, output_dir: str, tool_url: str) -> dict[str, object]:
    return {
        "slug": slug,
        "output_dir": output_dir,
        "status": "pending_browseract_seed",
        "workflow_kind": "page_extract",
        "auth_flow": "direct",
        "runtime_input_name": "page_url",
        "tool_url": tool_url,
        "authorized_credential_queries": list(_ONEMIN_AUTHORIZED_CREDENTIAL_QUERIES),
        "blocked_url_markers": [
            "tawk.to",
            "growthbook",
            "google-analytics.com",
            "region1.google-analytics.com",
            "otlp.1min.ai",
            "appleid.cdn-apple.com",
        ],
    }


def _onemin_login_modal_nodes() -> tuple[list[dict[str, object]], list[list[str]], str]:
    nodes: list[dict[str, object]] = [
        {
            "id": "open_login",
            "type": "visit_page",
            "label": "Open Login",
            "config": {"url": _ONEMIN_LOGIN_URL},
        },
        {
            "id": "wait_login_entry",
            "type": "wait",
            "label": "Wait Login Entry",
            "config": {
                "selector": _ONEMIN_LOGIN_ENTRY_SELECTOR,
                "timeout_ms": 5000,
                "optional": True,
            },
        },
        {
            "id": "open_login_entry",
            "type": "click",
            "label": "Open Login Entry",
            "config": {
                "selector": _ONEMIN_LOGIN_ENTRY_SELECTOR,
                "optional": True,
                "wait_timeout_ms": 2500,
                "dom_click": True,
                "react_click": True,
                "post_click_wait_ms": 1200,
            },
        },
        {
            "id": "wait_login_form",
            "type": "wait",
            "label": "Wait Login Form",
            "config": {
                "selector": _ONEMIN_EMAIL_SELECTOR,
                "timeout_ms": 45000,
            },
        },
        {
            "id": "email",
            "type": "input_text",
            "label": "Email",
            "config": {
                "selector": _ONEMIN_EMAIL_SELECTOR,
                "value_from_secret": "browseract_username",
            },
        },
        {
            "id": "password",
            "type": "input_text",
            "label": "Password",
            "config": {
                "selector": _ONEMIN_PASSWORD_SELECTOR,
                "value_from_secret": "browseract_password",
            },
        },
        {
            "id": "submit",
            "type": "submit_login_form",
            "label": "Submit Login",
            "config": {
                "selector": _ONEMIN_SUBMIT_SELECTOR,
                "password_selector": _ONEMIN_PASSWORD_SELECTOR,
                "react_click": True,
                "auth_advance_timeout_ms": 12000,
                "pre_submit_cookie_name": "cf_clearance",
                "pre_submit_cookie_timeout_ms": 25000,
                "pre_submit_wait_ms": 3000,
                "submit_retry_count": 1,
                "submit_retry_backoff_ms": 8000,
            },
        },
        {
            "id": "wait_authenticated",
            "type": "wait",
            "label": "Wait Authenticated",
            "config": {
                "selector": _ONEMIN_PASSWORD_SELECTOR,
                "state": "hidden",
                "timeout_ms": 45000,
                "optional": True,
            },
        },
    ]
    edges = [
        ["open_login", "wait_login_entry"],
        ["wait_login_entry", "open_login_entry"],
        ["open_login_entry", "wait_login_form"],
        ["wait_login_form", "email"],
        ["email", "password"],
        ["password", "submit"],
        ["submit", "wait_authenticated"],
    ]
    return nodes, edges, "wait_authenticated"


def _onemin_dismiss_overlay_nodes(previous: str) -> tuple[list[dict[str, object]], list[list[str]], str]:
    nodes: list[dict[str, object]] = []
    edges: list[list[str]] = []
    last = previous
    for index, selector in enumerate(_ONEMIN_CLOSE_SELECTORS, start=1):
        wait_id = f"wait_dismiss_overlay_{index:02d}"
        click_id = f"dismiss_overlay_{index:02d}"
        nodes.extend(
            [
                {
                    "id": wait_id,
                    "type": "wait",
                    "label": f"Wait Dismiss Overlay {index}",
                    "config": {
                        "selector": selector,
                        "timeout_ms": 2500,
                        "optional": True,
                    },
                },
                {
                    "id": click_id,
                    "type": "click",
                    "label": f"Dismiss Overlay {index}",
                    "config": {
                        "selector": selector,
                        "optional": True,
                        "wait_timeout_ms": 1500,
                    },
                },
            ]
        )
        edges.extend([[last, wait_id], [wait_id, click_id]])
        last = click_id
    return nodes, edges, last


def _onemin_workflow_inputs() -> list[dict[str, str]]:
    return [
        {
            "name": "browseract_username",
            "description": "1min login email for the selected account.",
        },
        {
            "name": "browseract_password",
            "description": "1min login password for the selected account.",
        },
        {
            "name": "page_url",
            "description": "Optional target page override for the selected 1min surface.",
        },
    ]


def _onemin_billing_usage_workflow_spec(*, output_dir: str) -> dict[str, object]:
    nodes, edges, last_login_node = _onemin_login_modal_nodes()
    nodes.extend(
        [
            {
                "id": "open_billing_usage",
                "type": "visit_page",
                "label": "Open Billing Usage",
                "config": {
                    "url": _ONEMIN_BILLING_USAGE_URL,
                    "value_from_input": "page_url",
                },
            },
            {
                "id": "wait_billing_usage",
                "type": "wait",
                "label": "Wait Billing Usage",
                "config": {"selector": "main, body", "timeout_ms": 45000},
            },
        ]
    )
    edges.extend(
        [
            [last_login_node, "open_billing_usage"],
            ["open_billing_usage", "wait_billing_usage"],
        ]
    )
    dismiss_nodes, dismiss_edges, last_node = _onemin_dismiss_overlay_nodes("wait_billing_usage")
    nodes.extend(dismiss_nodes)
    edges.extend(dismiss_edges)
    nodes.extend(
        [
            {
                "id": "extract_billing_settings",
                "type": "extract",
                "label": "Extract Billing Settings",
                "config": {
                    "selector": "main, body",
                    "field_name": "billing_settings_page",
                    "mode": "text",
                },
            },
            {
                "id": "extract_usage_records",
                "type": "extract",
                "label": "Extract Usage Records",
                "config": {
                    "selector": "table, main, body",
                    "field_name": "usage_records_page",
                    "mode": "text",
                },
            },
            {
                "id": "extract_pre_bonus_page",
                "type": "extract",
                "label": "Extract Billing Page Before Bonus",
                "config": {
                    "selector": "main, body",
                    "field_name": "billing_usage_pre_bonus_page",
                    "mode": "text",
                },
            },
            {
                "id": "wait_unlock_free_credits",
                "type": "wait",
                "label": "Wait Unlock Free Credits",
                "config": {
                    "selector": 'button:has-text("Unlock Free Credits"), [role=button]:has-text("Unlock Free Credits")',
                    "timeout_ms": 2500,
                    "optional": True,
                },
            },
            {
                "id": "unlock_free_credits",
                "type": "click",
                "label": "Unlock Free Credits",
                "config": {
                    "selector": 'button:has-text("Unlock Free Credits"), [role=button]:has-text("Unlock Free Credits")',
                    "optional": True,
                    "wait_timeout_ms": 1500,
                },
            },
            {
                "id": "wait_bonus_surface",
                "type": "wait",
                "label": "Wait Bonus Surface",
                "config": {"selector": "main, body", "timeout_ms": 45000},
            },
            {
                "id": "extract_billing_bonus_page",
                "type": "extract",
                "label": "Extract Billing Page After Bonus",
                "config": {
                    "selector": "main, body",
                    "field_name": "billing_usage_bonus_page",
                    "mode": "text",
                },
            },
            {
                "id": "output_result",
                "type": "output",
                "label": "Output Result",
                "config": {
                    "field_name": "billing_usage_bonus_page",
                },
            },
        ]
    )
    edges.extend(
        [
            [last_node, "extract_billing_settings"],
            ["extract_billing_settings", "extract_usage_records"],
            ["extract_usage_records", "extract_pre_bonus_page"],
            ["extract_pre_bonus_page", "wait_unlock_free_credits"],
            ["wait_unlock_free_credits", "unlock_free_credits"],
            ["unlock_free_credits", "wait_bonus_surface"],
            ["wait_bonus_surface", "extract_billing_bonus_page"],
            ["extract_billing_bonus_page", "output_result"],
        ]
    )
    return {
        "workflow_name": "1min Billing Usage Reader",
        "description": (
            "Sign in to 1min.AI, extract billing settings and usage records, capture the "
            "full billing page before and after the free-credit surface, and publish the "
            "post-click page for stable balance, burn, and bonus normalization."
        ),
        "publish": True,
        "mcp_ready": False,
        "inputs": _onemin_workflow_inputs(),
        "nodes": nodes,
        "edges": edges,
        "meta": _onemin_meta(
            slug="onemin_billing_usage_reader_live",
            output_dir=output_dir,
            tool_url=_ONEMIN_BILLING_USAGE_URL,
        ),
    }


def _onemin_members_workflow_spec(*, output_dir: str) -> dict[str, object]:
    nodes, edges, last_login_node = _onemin_login_modal_nodes()
    nodes.extend(
        [
            {
                "id": "open_members",
                "type": "visit_page",
                "label": "Open Members",
                "config": {
                    "url": _ONEMIN_MEMBERS_URL,
                    "value_from_input": "page_url",
                },
            },
            {
                "id": "wait_members",
                "type": "wait",
                "label": "Wait Members",
                "config": {"selector": "main, body", "timeout_ms": 45000},
            },
        ]
    )
    edges.extend(
        [
            [last_login_node, "open_members"],
            ["open_members", "wait_members"],
        ]
    )
    dismiss_nodes, dismiss_edges, last_node = _onemin_dismiss_overlay_nodes("wait_members")
    nodes.extend(dismiss_nodes)
    edges.extend(dismiss_edges)
    nodes.extend(
        [
            {
                "id": "extract_members",
                "type": "extract",
                "label": "Extract Members",
                "config": {
                    "selector": "main, body",
                    "field_name": "members_page",
                    "mode": "text",
                },
            },
            {
                "id": "output_result",
                "type": "output",
                "label": "Output Result",
                "config": {
                    "field_name": "members_page",
                },
            },
        ]
    )
    edges.extend(
        [
            [last_node, "extract_members"],
            ["extract_members", "output_result"],
        ]
    )
    return {
        "workflow_name": "1min Members Reconciliation Reader",
        "description": (
            "Sign in to 1min.AI, open the members surface, dismiss overlays, and extract "
            "the visible roster and status cues for owner reconciliation."
        ),
        "publish": True,
        "mcp_ready": False,
        "inputs": _onemin_workflow_inputs(),
        "nodes": nodes,
        "edges": edges,
        "meta": _onemin_meta(
            slug="onemin_members_reconciliation_live",
            output_dir=output_dir,
            tool_url=_ONEMIN_MEMBERS_URL,
        ),
    }


_TEMPLATES: tuple[BrowserActUiTemplateDefinition, ...] = (
    BrowserActUiTemplateDefinition(
        template_key="approvethis_queue_reader",
        workflow_name="ApproveThis Queue Reader",
        description="Open the logged-in ApproveThis queue/dashboard and extract the pending approvals view without relying on manual clicks.",
        login_url="https://app.approvethis.com/login",
        tool_url="",
        workflow_kind="page_extract",
        authorized_credential_queries=("approvethis.com",),
        wait_selector="main, table, [data-testid='approvals-list']",
        result_selector="main",
    ),
    BrowserActUiTemplateDefinition(
        template_key="metasurvey_results_reader",
        workflow_name="MetaSurvey Results Reader",
        description="Open a logged-in MetaSurvey survey or results page, dismiss overlays, and extract the visible survey summary/results content.",
        login_url="https://app.getmetasurvey.com/login/",
        tool_url="",
        workflow_kind="page_extract",
        runtime_input_name="survey_url",
        authorized_credential_queries=("metasurvey",),
        wait_selector="main, article, [data-testid='survey-results']",
        result_selector="main",
    ),
    BrowserActUiTemplateDefinition(
        template_key="nonverbia_workspace_reader",
        workflow_name="Nonverbia Workspace Reader",
        description="Open the logged-in Nonverbia workspace and extract the current writing surface, options, and visible generated output.",
        login_url="https://app.nonverbia.com",
        tool_url="",
        workflow_kind="page_extract",
        runtime_input_name="page_url",
        authorized_credential_queries=("nonverbia.com",),
        wait_selector="main, [role='main'], body",
        result_selector="main, [role='main'], body",
    ),
    BrowserActUiTemplateDefinition(
        template_key="documentation_ai_workspace_reader",
        workflow_name="Documentation AI Workspace Reader",
        description="Open the Documentation.AI workspace or docs surface and extract the visible document-generation workspace state for later automation refinement.",
        login_url="https://dashboard.documentation.ai/login",
        tool_url="",
        workflow_kind="page_extract",
        auth_flow="google_oauth",
        google_entry_selector='button:has-text("Continue with Google"), a:has-text("Continue with Google"), button:has-text("Google"), a:has-text("Google")',
        runtime_input_name="page_url",
        authorized_credential_queries=("google.com",),
        wait_selector="main, article, [role='main'], body",
        result_selector="main, article, [role='main'], body",
    ),
    BrowserActUiTemplateDefinition(
        template_key="invoiless_workspace_reader",
        workflow_name="Invoiless Workspace Reader",
        description="Open the logged-in Invoiless workspace and extract the visible invoice dashboard or draft surface for later EA automation.",
        login_url="https://app.invoiless.com/login",
        tool_url="",
        workflow_kind="page_extract",
        runtime_input_name="page_url",
        wait_selector="main, [role='main'], body",
        result_selector="main, [role='main'], body",
    ),
    BrowserActUiTemplateDefinition(
        template_key="markupgo_workspace_reader",
        workflow_name="MarkupGo Workspace Reader",
        description="Open the logged-in MarkupGo workspace and extract the visible markup or asset-generation surface so EA can steer the UI with explicit evidence.",
        login_url="https://markupgo.com/login",
        tool_url="",
        workflow_kind="page_extract",
        runtime_input_name="page_url",
        wait_selector="main, [role='main'], body",
        result_selector="main, [role='main'], body",
    ),
    BrowserActUiTemplateDefinition(
        template_key="paperguide_workspace_reader",
        workflow_name="Paperguide Workspace Reader",
        description="Open the logged-in Paperguide workspace and extract the visible research, note, or paper-management surface for operator review.",
        login_url="https://paperguide.ai/login/",
        tool_url="",
        workflow_kind="page_extract",
        auth_flow="google_oauth",
        google_entry_selector="button:has-text(\"Login with Google\"), a:has-text(\"Login with Google\")",
        runtime_input_name="page_url",
        authorized_credential_queries=("google.com",),
        wait_selector="main, article, [role='main'], body",
        result_selector="main, article, [role='main'], body",
    ),
    BrowserActUiTemplateDefinition(
        template_key="apixdrive_workspace_reader",
        workflow_name="ApiX-Drive Workspace Reader",
        description="Open the logged-in ApiX-Drive workspace and extract the visible flow, connector, or automation setup surface.",
        login_url="https://apix-drive.com/en/login",
        tool_url="",
        workflow_kind="page_extract",
        auth_flow="google_oauth",
        google_auth_url="https://accounts.google.com/o/oauth2/v2/auth?client_id=515159707774-9ohda5a8j3ijrol2vc0m5tqq6jiju9f1.apps.googleusercontent.com&scope=profile%20email&response_type=code&redirect_uri=https://apix-drive.com/google-callback-login&prompt=select_account+consent&state=en",
        runtime_input_name="page_url",
        authorized_credential_queries=("google.com",),
        wait_selector="main, [role='main'], body",
        result_selector="main, [role='main'], body",
    ),
    BrowserActUiTemplateDefinition(
        template_key="peekshot_workspace_reader",
        workflow_name="PeekShot Workspace Reader",
        description="Open the PeekShot workspace or target preview surface and extract the visible capture controls and output state.",
        login_url="https://dashboard.peekshot.com/",
        tool_url="",
        workflow_kind="page_extract",
        runtime_input_name="page_url",
        authorized_credential_queries=("peekshot.com",),
        wait_selector="main, [role='main'], body",
        result_selector="main, [role='main'], body",
    ),
    BrowserActUiTemplateDefinition(
        template_key="unmixr_workspace_reader",
        workflow_name="Unmixr AI Workspace Reader",
        description="Open the logged-in Unmixr AI workspace and extract the visible generation surface so EA can steer voice, content, or media flows.",
        login_url="https://app.unmixr.com",
        tool_url="",
        workflow_kind="page_extract",
        runtime_input_name="page_url",
        wait_selector="main, [role='main'], body",
        result_selector="main, [role='main'], body",
    ),
    BrowserActUiTemplateDefinition(
        template_key="vizologi_workspace_reader",
        workflow_name="Vizologi Workspace Reader",
        description="Open the logged-in Vizologi workspace and extract the visible strategy canvas or market-intelligence surface.",
        login_url="https://app.vizologi.com/user/login?lang=en",
        tool_url="",
        workflow_kind="page_extract",
        runtime_input_name="page_url",
        authorized_credential_queries=("vizologi.com",),
        wait_selector="main, [role='main'], body",
        result_selector="main, [role='main'], body",
    ),
    BrowserActUiTemplateDefinition(
        template_key="onemin_billing_usage_reader_live",
        workflow_name="1min Billing Usage Reader",
        description="Open the logged-in 1min billing usage surface and extract the visible credit, top-up, and billing state.",
        login_url=_ONEMIN_LOGIN_URL,
        tool_url=_ONEMIN_BILLING_USAGE_URL,
        workflow_kind="page_extract",
        runtime_input_name="page_url",
        authorized_credential_queries=_ONEMIN_AUTHORIZED_CREDENTIAL_QUERIES,
        direct_pre_auth_dismiss_selectors=_ONEMIN_CLOSE_SELECTORS[:2],
        direct_login_entry_selector=_ONEMIN_LOGIN_ENTRY_SELECTOR,
        direct_login_entry_dom_click=True,
        direct_email_selector=_ONEMIN_EMAIL_SELECTOR,
        direct_password_selector=_ONEMIN_PASSWORD_SELECTOR,
        direct_submit_selector=_ONEMIN_SUBMIT_SELECTOR,
        wait_selector="main, body",
        result_selector="main, body",
        title_selector="",
        result_field_name="billing_usage_bonus_page",
        include_dismiss_nodes=True,
    ),
    BrowserActUiTemplateDefinition(
        template_key="onemin_members_reconciliation_live",
        workflow_name="1min Members Reconciliation Reader",
        description="Open the logged-in 1min members surface and extract the visible member roster, statuses, and credit-limit hints for owner reconciliation.",
        login_url=_ONEMIN_LOGIN_URL,
        tool_url=_ONEMIN_MEMBERS_URL,
        workflow_kind="page_extract",
        runtime_input_name="page_url",
        authorized_credential_queries=_ONEMIN_AUTHORIZED_CREDENTIAL_QUERIES,
        direct_pre_auth_dismiss_selectors=_ONEMIN_CLOSE_SELECTORS[:2],
        direct_login_entry_selector=_ONEMIN_LOGIN_ENTRY_SELECTOR,
        direct_login_entry_dom_click=True,
        direct_email_selector=_ONEMIN_EMAIL_SELECTOR,
        direct_password_selector=_ONEMIN_PASSWORD_SELECTOR,
        direct_submit_selector=_ONEMIN_SUBMIT_SELECTOR,
        wait_selector="main, body",
        result_selector="main, body",
        title_selector="",
        result_field_name="members_page",
        include_dismiss_nodes=True,
    ),
)


def browseract_ui_template_definitions() -> tuple[BrowserActUiTemplateDefinition, ...]:
    return _TEMPLATES


def browseract_ui_template_by_key(template_key: str) -> BrowserActUiTemplateDefinition | None:
    normalized = str(template_key or "").strip().lower()
    for template in _TEMPLATES:
        if normalized == template.template_key:
            return template
    return None


def browseract_ui_template_spec(template_key: str, *, output_dir: str = "/docker/fleet/state/browseract_bootstrap") -> dict[str, object]:
    normalized = str(template_key or "").strip().lower()
    if normalized == "onemin_billing_usage_reader_live":
        return _onemin_billing_usage_workflow_spec(output_dir=output_dir)
    if normalized == "onemin_members_reconciliation_live":
        return _onemin_members_workflow_spec(output_dir=output_dir)
    template = browseract_ui_template_by_key(template_key)
    if template is None:
        raise KeyError(f"unknown_browseract_ui_template:{template_key}")
    return template.workflow_spec(output_dir=output_dir)
