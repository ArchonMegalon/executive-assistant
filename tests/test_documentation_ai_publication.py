from __future__ import annotations

from datetime import datetime, timezone

from app.services.documentation_ai_publication import build_documentation_ai_publication_packet


NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)


def _docs() -> list[dict[str, object]]:
    return [
        {
            "path": ".codex-design/ea/START_HERE.md",
            "source_type": "source_controlled_ea_docs",
            "approval_status": "approved",
            "data_classification": "public",
            "content": "# Start Here\n\nEA starts with one morning memo and one review queue.",
        },
        {
            "path": ".codex-design/ea/SECURITY.md",
            "source_type": "approved_security_trust_center",
            "approval_status": "approved",
            "data_classification": "public",
            "content": "# Security\n\nNothing sensitive sends without review.",
        },
    ]


def test_documentation_ai_publication_requires_source_bound_approved_docs() -> None:
    packet = build_documentation_ai_publication_packet(
        _docs(),
        site_key="ea-customer-help",
        source_git_head="abc123",
        llms_txt="# EA Docs\n\n- /start-here",
        link_check={"status": "pass", "checked_url_count": 12, "broken_links": []},
        now=NOW,
    )

    assert packet["status"] == "projection_ready"
    assert packet["docs_projection_allowed"] is True
    assert packet["provider_agent_writeback_allowed"] is False
    assert packet["publication_truth_allowed"] is False
    assert packet["workspace_data_allowed"] is False
    assert packet["validation"]["documentation_truth_owner"] == "git"  # type: ignore[index]
    assert packet["validation"]["source_git_head"] == "pass"  # type: ignore[index]
    assert packet["llms_txt"]["present"] is True  # type: ignore[index]
    assert len(packet["source_tree_fingerprint"]) == 64


def test_documentation_ai_publication_blocks_unapproved_docs() -> None:
    docs = _docs()
    docs[0]["approval_status"] = "draft"

    packet = build_documentation_ai_publication_packet(
        docs,
        site_key="ea-customer-help",
        source_git_head="abc123",
        llms_txt="# EA Docs",
        link_check={"status": "pass", "broken_links": []},
        now=NOW,
    )

    assert packet["status"] == "blocked"
    assert "doc_approval_required" in packet["blocking_reasons"]
    assert packet["validation"]["approved_markdown_docs"] == "fail"  # type: ignore[index]


def test_documentation_ai_publication_blocks_private_workspace_sources_and_secrets() -> None:
    private_doc = {
        "path": "support/private-case.md",
        "source_type": "customer_support_ticket",
        "approval_status": "approved",
        "data_classification": "public",
        "content": "# Support case\n\nCustomer details.",
    }
    secret_doc = {
        "path": "operator/secret.md",
        "source_type": "approved_operator_runbook",
        "approval_status": "approved",
        "data_classification": "public",
        "content": "API_KEY=sk_live_secret",
    }

    private_packet = build_documentation_ai_publication_packet(
        [private_doc],
        site_key="ea-operator",
        source_git_head="abc123",
        llms_txt="# EA Docs",
        link_check={"status": "pass", "broken_links": []},
        now=NOW,
    )
    assert private_packet["status"] == "blocked"
    assert "forbidden_source_type_customer_support_ticket" in private_packet["blocking_reasons"]

    secret_packet = build_documentation_ai_publication_packet(
        [secret_doc],
        site_key="ea-operator",
        source_git_head="abc123",
        llms_txt="# EA Docs",
        link_check={"status": "pass", "broken_links": []},
        now=NOW,
    )
    assert secret_packet["status"] == "blocked"
    assert "secret_marker_detected" in secret_packet["blocking_reasons"]


def test_documentation_ai_publication_requires_head_llms_and_link_check() -> None:
    packet = build_documentation_ai_publication_packet(
        _docs(),
        site_key="ea-customer-help",
        source_git_head="",
        llms_txt="",
        link_check={"status": "fail", "broken_links": ["/missing"]},
        now=NOW,
    )

    assert packet["status"] == "blocked"
    assert {"source_git_head_required", "llms_txt_required", "link_check_failed"} <= set(packet["blocking_reasons"])
    assert packet["validation"]["source_git_head"] == "fail"  # type: ignore[index]
    assert packet["validation"]["llms_txt"] == "fail"  # type: ignore[index]
    assert packet["validation"]["link_check"] == "fail"  # type: ignore[index]


def test_documentation_ai_publication_blocks_provider_writeback() -> None:
    packet = build_documentation_ai_publication_packet(
        _docs(),
        site_key="ea-customer-help",
        source_git_head="abc123",
        llms_txt="# EA Docs",
        link_check={"status": "pass", "broken_links": []},
        provider_agent_writeback_enabled=True,
        now=NOW,
    )

    assert packet["status"] == "blocked"
    assert "provider_agent_writeback_enabled" in packet["blocking_reasons"]
    assert packet["provider_agent_writeback_allowed"] is False
    assert packet["validation"]["provider_agent_writeback"] == "fail"  # type: ignore[index]
