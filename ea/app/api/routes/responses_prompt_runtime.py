from __future__ import annotations


def tool_shim_is_staged_local_orientation_prompt(text: str) -> bool:
    prompt = str(text or "")
    if not prompt:
        return False
    return any(
        marker in prompt
        for marker in (
            "Run these exact commands first:",
            "Safe first commands if you need orientation",
            "Read these files directly first:",
            "Read from disk before coding:",
        )
    )


def tool_shim_is_operator_fleet_unblock_prompt(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return (
        "operator-prepared fleet unblock context:" in normalized
        or (
            "scope: patch only the codexea shim, ea endpoints, and the 1min manager." in normalized
            and "do not work shard backlog content" in normalized
        )
    )


def tool_shim_is_package_work_prompt(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "operator-prepared fleet unblock context:",
            "active slice override",
            "system re-entry.",
            "read from disk before coding:",
            "then inspect the current repository state before changing anything.",
            "current slice:",
            "owner repo for this pass:",
            "package scope:",
            "isolated worktree:",
            "allowed paths:",
            "denied paths:",
            "owned surfaces:",
            "spider routing notes:",
            "unread feedback files to incorporate in order:",
        )
    )


def tool_shim_is_operator_readiness_remedy_prompt(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return (
        "operator-prepared readiness remedy context:" in normalized
        or (
            "scope: patch only the targeted product proof surface implied by the prompt." in normalized
            and "stay on product proof generation, verification" in normalized
        )
    )


def tool_shim_is_operator_gap_audit_prompt(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return "operator-prepared gap audit context:" in normalized


def tool_shim_is_operator_gap_fix_prompt(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return "operator-prepared gap fix context:" in normalized
