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
        nodes = [
            {
                "id": "wait_login_form",
                "type": "wait",
                "label": "Wait Login Form",
                "config": {
                    "selector": "input[type=email], input[name=email], input[name=identifier], input[autocomplete='email'], input[autocomplete='username'], input[type=text][name=email], input[type=text][placeholder*='mail' i]",
                    "timeout_ms": 45000,
                },
            },
            {
                "id": "email",
                "type": "input_text",
                "label": "Email",
                "config": {
                    "selector": "input[type=email], input[name=email], input[name=identifier], input[autocomplete='email'], input[autocomplete='username'], input[type=text][name=email], input[type=text][placeholder*='mail' i]",
                    "value_from_secret": "browseract_username",
                },
            },
            {
                "id": "password",
                "type": "input_text",
                "label": "Password",
                "config": {
                    "selector": "input[type=password], input[name=password], input[name=Passwd], input[autocomplete='current-password'], input[placeholder*='Password' i]",
                    "value_from_secret": "browseract_password",
                },
            },
            {
                "id": "submit",
                "type": "click",
                "label": "Submit Login",
                "config": {
                    "selector": "form button[type=submit], form input[type=submit], button:has-text(\"Sign In\"), button:has-text(\"Log In\"), button:has-text(\"Login\"), button:has-text(\"Continue\"), button:has-text(\"LOG IN\")"
                },
            },
            {
                "id": "wait_authenticated",
                "type": "wait",
                "label": "Wait Authenticated",
                "config": {
                    "selector": "input[type=password], input[name=password], input[name=Passwd], input[autocomplete='current-password']",
                    "state": "hidden",
                    "timeout_ms": 45000,
                },
            },
        ]
        edges = [
            ["open_login", "wait_login_form"],
            ["wait_login_form", "email"],
            ["email", "password"],
            ["password", "submit"],
            ["submit", "wait_authenticated"],
        ]
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
    template = browseract_ui_template_by_key(template_key)
    if template is None:
        raise KeyError(f"unknown_browseract_ui_template:{template_key}")
    return template.workflow_spec(output_dir=output_dir)
