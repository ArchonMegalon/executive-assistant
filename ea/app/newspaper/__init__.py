from __future__ import annotations

from typing import Any


async def build_issue_for_brief(**kwargs: Any):
    from .pipeline import build_issue_for_brief as _impl

    return await _impl(**kwargs)


def render_issue_html(issue: dict):
    from .render import render_issue_html as _impl

    return _impl(issue)


def validate_issue(issue: dict):
    from .validate import validate_issue as _impl

    return _impl(issue)


__all__ = ["build_issue_for_brief", "render_issue_html", "validate_issue"]
