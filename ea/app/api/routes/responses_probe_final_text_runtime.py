from __future__ import annotations


def _finding_lines(
    findings: list[dict[str, object]],
    *,
    limit: int,
    include_path: bool = False,
) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(findings[:limit], start=1):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "info").strip().upper()
        category = str(item.get("category") or "gap").strip()
        summary_text = str(item.get("summary") or "").strip()
        path = str(item.get("path") or "").strip() if include_path else ""
        detail = str(item.get("detail") or "").strip()
        segment = f"{index}. {severity} {category}: {summary_text}"
        if path:
            segment += f" [{path}]"
        if detail:
            segment += f" {detail}"
        lines.append(segment)
    return lines


def tool_shim_gap_audit_final_text(summary: dict[str, object]) -> str | None:
    if str(summary.get("probe_kind") or "").strip().lower() != "gap_audit":
        return None
    findings = summary.get("findings")
    if not isinstance(findings, list):
        return None
    notes = summary.get("notes")
    note_rows = [str(item).strip() for item in notes if str(item).strip()] if isinstance(notes, list) else []
    lines: list[str] = []
    if findings:
        lines.append("Gap audit findings:")
        lines.extend(_finding_lines(findings, limit=6, include_path=True))
    if note_rows:
        lines.append("Notes:")
        for note in note_rows[:3]:
            lines.append(f"- {note}")
    if not lines:
        return None
    return "\n".join(lines)


def tool_shim_ui_parity_audit_final_text(summary: dict[str, object]) -> str | None:
    if str(summary.get("probe_kind") or "").strip().lower() != "ui_parity_audit":
        return None
    total_elements = int(summary.get("total_elements") or 0)
    visual_yes = int(summary.get("visual_yes_count") or 0)
    visual_no = int(summary.get("visual_no_count") or 0)
    behavioral_yes = int(summary.get("behavioral_yes_count") or 0)
    behavioral_no = int(summary.get("behavioral_no_count") or 0)
    extras_present = int(summary.get("chummer6_only_extra_present_count") or 0)
    removable_extras = int(summary.get("removable_extra_present_count") or 0)
    report_json_path = str(summary.get("report_json_path") or "").strip()
    report_markdown_path = str(summary.get("report_markdown_path") or "").strip()
    coverage_gap_keys = [str(item).strip() for item in (summary.get("coverage_gap_keys") or []) if str(item).strip()]
    findings = summary.get("findings") if isinstance(summary.get("findings"), list) else []
    notes = [str(item).strip() for item in (summary.get("notes") or []) if str(item).strip()]
    lines = [
        "UI parity audit result:",
        f"- total_elements={total_elements}",
        f"- visual_yes_no={visual_yes}/{visual_no}",
        f"- behavioral_yes_no={behavioral_yes}/{behavioral_no}",
        f"- chummer6_only_extras_present={extras_present}",
        f"- removable_extras_present={removable_extras}",
    ]
    if coverage_gap_keys:
        lines.append(f"- coverage_gap_keys={coverage_gap_keys}")
    if report_json_path:
        lines.append(f"- report_json={report_json_path}")
    if report_markdown_path:
        lines.append(f"- report_markdown={report_markdown_path}")
    if findings:
        lines.append("Top findings:")
        lines.extend(_finding_lines(findings, limit=8))
    if notes:
        lines.append("Notes:")
        for note in notes[:3]:
            lines.append(f"- {note}")
    return "\n".join(lines)


def tool_shim_parity_build_final_text(summary: dict[str, object]) -> str | None:
    if str(summary.get("probe_kind") or "").strip().lower() != "parity_build":
        return None
    release_version = str(summary.get("release_version") or "").strip()
    applied_steps = [str(item).strip() for item in (summary.get("applied_steps") or []) if str(item).strip()]
    parity_report_path = str(summary.get("parity_report_path") or "").strip()
    parity_summary = summary.get("parity_summary") if isinstance(summary.get("parity_summary"), dict) else {}
    remaining_findings = summary.get("remaining_findings") if isinstance(summary.get("remaining_findings"), list) else []
    lines = ["Parity build result:"]
    if release_version:
        lines.append(f"- release_version={release_version}")
    if applied_steps:
        lines.append("Applied:")
        for step in applied_steps[:10]:
            lines.append(f"- {step}")
    if parity_summary:
        lines.append(
            "- parity_counts="
            f"visual {int(parity_summary.get('visual_yes_count') or 0)}/{int(parity_summary.get('visual_no_count') or 0)}"
            f", behavioral {int(parity_summary.get('behavioral_yes_count') or 0)}/{int(parity_summary.get('behavioral_no_count') or 0)}"
        )
    if parity_report_path:
        lines.append(f"- parity_report={parity_report_path}")
    if remaining_findings:
        lines.append("Remaining findings:")
        lines.extend(_finding_lines(remaining_findings, limit=8))
    return "\n".join(lines)


def tool_shim_gap_fix_final_text(summary: dict[str, object]) -> str | None:
    if str(summary.get("probe_kind") or "").strip().lower() != "gap_fix":
        return None
    step_results = summary.get("step_results")
    applied_steps = [str(item).strip() for item in (summary.get("applied_steps") or []) if str(item).strip()]
    status_summary = summary.get("status_summary") if isinstance(summary.get("status_summary"), dict) else {}
    remaining_findings = summary.get("remaining_findings") if isinstance(summary.get("remaining_findings"), list) else []
    lines: list[str] = ["Gap fix result:"]
    if applied_steps:
        lines.append("Applied:")
        for step in applied_steps[:8]:
            lines.append(f"- {step}")
    if isinstance(step_results, list):
        failing_steps = []
        for item in step_results:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").strip().lower()
            if status in {"fail", "timeout"}:
                failing_steps.append(f"{item.get('name')}: {status}")
        if failing_steps:
            lines.append("Incomplete steps:")
            for row in failing_steps[:5]:
                lines.append(f"- {row}")
    current_parts: list[str] = []
    for key in (
        "workflow_gate",
        "visual_gate",
        "windows_gate",
        "linux_gate",
        "macos_gate",
        "desktop_executable_gate",
        "flagship_readiness",
    ):
        row = status_summary.get(key)
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip()
        if status:
            current_parts.append(f"{key}={status}")
    if current_parts:
        lines.append("Current status:")
        lines.append("- " + ", ".join(current_parts))
    if remaining_findings:
        lines.append("Remaining findings:")
        lines.extend(_finding_lines(remaining_findings, limit=5))
    return "\n".join(lines)
