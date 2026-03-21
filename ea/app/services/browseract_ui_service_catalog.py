from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserActUiServiceDefinition:
    service_key: str
    capability_key: str
    tool_name: str
    skill_key: str
    task_key: str
    name: str
    description: str
    deliverable_type: str
    action_kind: str
    output_label: str
    browseract_service_names: tuple[str, ...]
    tags: tuple[str, ...]
    aliases: tuple[str, ...]
    binding_workflow_id_keys: tuple[str, ...]
    binding_run_url_keys: tuple[str, ...]
    required_top_level_inputs: tuple[str, ...]
    required_runtime_inputs: tuple[str, ...]
    payload_to_runtime_inputs: dict[str, str]
    input_properties: dict[str, object]
    worker_script_name: str = ""
    template_key: str = ""

    def input_schema_json(self) -> dict[str, object]:
        properties = {
            "binding_id": {"type": "string"},
            "workflow_id": {"type": "string"},
            "run_url": {"type": "string"},
            "runtime_inputs_json": {"type": "object"},
            "timeout_seconds": {"type": "integer"},
            "result_title": {"type": "string"},
            "proxy_result": {"type": "boolean"},
        }
        properties.update(dict(self.input_properties))
        required = ["binding_id", *self.required_top_level_inputs]
        return {
            "type": "object",
            "required": required,
            "properties": properties,
        }

    def output_schema_json(self) -> dict[str, object]:
        return {
            "type": "object",
            "required": [
                "service_key",
                "result_title",
                "render_status",
                "tool_name",
                "action_kind",
            ],
            "properties": {
                "service_key": {"type": "string"},
                "result_title": {"type": "string"},
                "render_status": {"type": "string"},
                "asset_url": {"type": ["string", "null"]},
                "download_url": {"type": ["string", "null"]},
                "public_url": {"type": ["string", "null"]},
                "editor_url": {"type": ["string", "null"]},
                "asset_urls": {"type": "array", "items": {"type": "string"}},
                "workflow_id": {"type": ["string", "null"]},
                "task_id": {"type": ["string", "null"]},
                "requested_url": {"type": "string"},
                "structured_output_json": {"type": "object"},
            },
        }


def _workflow_keys(prefix: str, *extra: str) -> tuple[str, ...]:
    normalized = str(prefix or "").strip()
    values = [
        f"{normalized}_workflow_id",
        f"browseract_{normalized}_workflow_id",
        *extra,
    ]
    return tuple(value for value in values if value)


def _run_url_keys(prefix: str, *extra: str) -> tuple[str, ...]:
    normalized = str(prefix or "").strip()
    values = [
        f"{normalized}_run_url",
        f"browseract_{normalized}_run_url",
        *extra,
    ]
    return tuple(value for value in values if value)


def _template_reader_service(
    *,
    service_key: str,
    capability_key: str,
    tool_name: str,
    skill_key: str,
    task_key: str,
    name: str,
    description: str,
    deliverable_type: str,
    browseract_names: tuple[str, ...],
    aliases: tuple[str, ...],
    template_key: str,
    page_input_name: str = "",
    output_label: str = "workspace",
    action_kind: str = "workspace.capture",
) -> BrowserActUiServiceDefinition:
    input_properties: dict[str, object] = {}
    payload_to_runtime_inputs: dict[str, str] = {}
    required_runtime_inputs: tuple[str, ...] = ()
    if page_input_name:
        input_properties[page_input_name] = {"type": "string"}
        payload_to_runtime_inputs[page_input_name] = page_input_name
    return BrowserActUiServiceDefinition(
        service_key=service_key,
        capability_key=capability_key,
        tool_name=tool_name,
        skill_key=skill_key,
        task_key=task_key,
        name=name,
        description=description,
        deliverable_type=deliverable_type,
        action_kind=action_kind,
        output_label=output_label,
        browseract_service_names=browseract_names,
        tags=("browseract", "ui-only", "workspace", "template-backed"),
        aliases=aliases,
        binding_workflow_id_keys=_workflow_keys(service_key),
        binding_run_url_keys=_run_url_keys(service_key),
        required_top_level_inputs=(),
        required_runtime_inputs=required_runtime_inputs,
        payload_to_runtime_inputs=payload_to_runtime_inputs,
        input_properties=input_properties,
        worker_script_name="browseract_template_service_worker.py",
        template_key=template_key,
    )


_SERVICE_DEFINITIONS: tuple[BrowserActUiServiceDefinition, ...] = (
    BrowserActUiServiceDefinition(
        service_key="mootion_movie",
        capability_key="mootion_movie",
        tool_name="browseract.mootion_movie",
        skill_key="create_mootion_movie",
        task_key="create_mootion_movie",
        name="Create Mootion Movie",
        description="Steerable BrowserAct-backed Mootion movie generator for short clips, recap beats, NPC messages, and briefing videos.",
        deliverable_type="mootion_movie_packet",
        action_kind="movie.render",
        output_label="movie",
        browseract_service_names=("BrowserAct", "Mootion"),
        tags=("browseract", "mootion", "video", "movie", "ui-only"),
        aliases=("mootion", "movie", "video", "create_mootion_movie", "mootion_video"),
        binding_workflow_id_keys=(
            "mootion_movie_workflow_id",
            "browseract_mootion_movie_workflow_id",
            "mootion_briefing_renderer_workflow_id",
            "browseract_mootion_briefing_renderer_workflow_id",
        ),
        binding_run_url_keys=(
            "mootion_movie_run_url",
            "browseract_mootion_movie_run_url",
            "mootion_briefing_renderer_run_url",
            "browseract_mootion_briefing_renderer_run_url",
        ),
        required_top_level_inputs=("script_text",),
        required_runtime_inputs=("prompt",),
        payload_to_runtime_inputs={
            "script_text": "prompt",
            "visual_style": "visual_style",
            "camera_style": "camera_style",
            "aspect_ratio": "aspect_ratio",
            "duration_seconds": "duration_seconds",
            "voiceover_style": "voiceover_style",
            "music_mood": "music_mood",
            "caption_mode": "caption_mode",
            "language": "language",
            "scene_count": "scene_count",
            "shot_pacing": "shot_pacing",
            "title": "title",
            "audience": "audience",
            "hook_line": "hook_line",
            "closing_line": "closing_line",
            "platform_target": "platform_target",
            "cta": "cta",
        },
        input_properties={
            "script_text": {"type": "string"},
            "visual_style": {"type": "string"},
            "camera_style": {"type": "string"},
            "aspect_ratio": {"type": "string"},
            "duration_seconds": {"type": "integer"},
            "voiceover_style": {"type": "string"},
            "music_mood": {"type": "string"},
            "caption_mode": {"type": "string"},
            "language": {"type": "string"},
            "scene_count": {"type": "integer"},
            "shot_pacing": {"type": "string"},
            "title": {"type": "string"},
            "audience": {"type": "string"},
            "hook_line": {"type": "string"},
            "closing_line": {"type": "string"},
            "platform_target": {"type": "string"},
            "cta": {"type": "string"},
        },
        worker_script_name="mootion_movie_worker.py",
    ),
    BrowserActUiServiceDefinition(
        service_key="avomap_flyover",
        capability_key="avomap_flyover",
        tool_name="browseract.avomap_flyover",
        skill_key="create_avomap_flyover",
        task_key="create_avomap_flyover",
        name="Create AvoMap Flyover",
        description="Steerable BrowserAct-backed AvoMap flyover generator for route previews, exfil visualizations, and movement recap clips.",
        deliverable_type="avomap_flyover_packet",
        action_kind="map.flyover_render",
        output_label="flyover",
        browseract_service_names=("BrowserAct", "AvoMap"),
        tags=("browseract", "avomap", "map", "flyover", "ui-only"),
        aliases=("avomap", "flyover", "create_avomap_flyover", "route_flyover"),
        binding_workflow_id_keys=(
            "avomap_flyover_workflow_id",
            "browseract_avomap_flyover_workflow_id",
            "avomap_route_renderer_workflow_id",
            "browseract_avomap_route_renderer_workflow_id",
        ),
        binding_run_url_keys=(
            "avomap_flyover_run_url",
            "browseract_avomap_flyover_run_url",
            "avomap_route_renderer_run_url",
            "browseract_avomap_route_renderer_run_url",
        ),
        required_top_level_inputs=("route_data",),
        required_runtime_inputs=("route_data",),
        payload_to_runtime_inputs={
            "route_data": "route_data",
            "camera_style": "camera_style",
            "map_style": "map_style",
            "speed_profile": "speed_profile",
            "duration_seconds": "duration_seconds",
            "start_label": "start_label",
            "end_label": "end_label",
            "poi_json": "poi_json",
            "language": "language",
            "title": "title",
            "video_format": "video_format",
            "video_quality": "video_quality",
            "route_mode": "route_mode",
            "line_style": "line_style",
            "line_color": "line_color",
            "show_distance": "show_distance",
            "show_elevation": "show_elevation",
            "show_labels": "show_labels",
        },
        input_properties={
            "route_data": {"type": "string"},
            "camera_style": {"type": "string"},
            "map_style": {"type": "string"},
            "speed_profile": {"type": "string"},
            "duration_seconds": {"type": "integer"},
            "start_label": {"type": "string"},
            "end_label": {"type": "string"},
            "poi_json": {"type": ["object", "array", "string"]},
            "language": {"type": "string"},
            "title": {"type": "string"},
            "video_format": {"type": "string"},
            "video_quality": {"type": "string"},
            "route_mode": {"type": "string"},
            "line_style": {"type": "string"},
            "line_color": {"type": "string"},
            "show_distance": {"type": "boolean"},
            "show_elevation": {"type": "boolean"},
            "show_labels": {"type": "boolean"},
        },
        worker_script_name="avomap_flyover_worker.py",
    ),
    BrowserActUiServiceDefinition(
        service_key="booka_book",
        capability_key="booka_book",
        tool_name="browseract.booka_book",
        skill_key="create_booka_book",
        task_key="create_booka_book",
        name="Create Booka Book",
        description="Steerable BrowserAct-backed Booka or First Book AI generator for short books, guides, and booklet-style outputs.",
        deliverable_type="booka_book_packet",
        action_kind="book.generate",
        output_label="book",
        browseract_service_names=("BrowserAct", "Booka", "First Book AI"),
        tags=("browseract", "booka", "book", "ebook", "ui-only"),
        aliases=("booka", "book", "first_book_ai", "create_booka_book"),
        binding_workflow_id_keys=(
            "booka_book_workflow_id",
            "browseract_booka_book_workflow_id",
            "first_book_ai_workflow_id",
            "browseract_first_book_ai_workflow_id",
        ),
        binding_run_url_keys=(
            "booka_book_run_url",
            "browseract_booka_book_run_url",
            "first_book_ai_run_url",
            "browseract_first_book_ai_run_url",
        ),
        required_top_level_inputs=("book_prompt",),
        required_runtime_inputs=("book_prompt",),
        payload_to_runtime_inputs={
            "book_prompt": "book_prompt",
            "audience": "audience",
            "tone": "tone",
            "language": "language",
            "chapter_count": "chapter_count",
            "cover_style": "cover_style",
            "title": "title",
            "goal": "goal",
            "professional_background": "professional_background",
            "key_beliefs": "key_beliefs",
            "anecdotes": "anecdotes",
            "writing_sample": "writing_sample",
            "style_references": "style_references",
        },
        input_properties={
            "book_prompt": {"type": "string"},
            "audience": {"type": "string"},
            "tone": {"type": "string"},
            "language": {"type": "string"},
            "chapter_count": {"type": "integer"},
            "cover_style": {"type": "string"},
            "title": {"type": "string"},
            "goal": {"type": "string"},
            "professional_background": {"type": "string"},
            "key_beliefs": {"type": "string"},
            "anecdotes": {"type": "string"},
            "writing_sample": {"type": "string"},
            "style_references": {"type": "string"},
        },
        worker_script_name="booka_book_worker.py",
    ),
    _template_reader_service(
        service_key="approvethis_queue_reader",
        capability_key="approvethis_queue_reader",
        tool_name="browseract.approvethis_queue_reader",
        skill_key="read_approvethis_queue",
        task_key="read_approvethis_queue",
        name="Read ApproveThis Queue",
        description="Template-backed BrowserAct ApproveThis queue reader for approvals, pending decisions, and operator audit snapshots.",
        deliverable_type="approvethis_queue_packet",
        browseract_names=("BrowserAct", "ApproveThis"),
        aliases=("approvethis", "approval_queue", "read_approvethis_queue"),
        template_key="approvethis_queue_reader",
    ),
    _template_reader_service(
        service_key="metasurvey_results_reader",
        capability_key="metasurvey_results_reader",
        tool_name="browseract.metasurvey_results_reader",
        skill_key="read_metasurvey_results",
        task_key="read_metasurvey_results",
        name="Read MetaSurvey Results",
        description="Template-backed BrowserAct MetaSurvey reader for survey dashboards, individual survey result pages, and feedback snapshots.",
        deliverable_type="metasurvey_results_packet",
        browseract_names=("BrowserAct", "MetaSurvey"),
        aliases=("metasurvey", "survey_results", "read_metasurvey_results"),
        template_key="metasurvey_results_reader",
        page_input_name="survey_url",
    ),
    _template_reader_service(
        service_key="nonverbia_workspace_reader",
        capability_key="nonverbia_workspace_reader",
        tool_name="browseract.nonverbia_workspace_reader",
        skill_key="inspect_nonverbia_workspace",
        task_key="inspect_nonverbia_workspace",
        name="Inspect Nonverbia Workspace",
        description="Template-backed BrowserAct Nonverbia workspace reader for writing-surface inspection, option discovery, and output capture.",
        deliverable_type="nonverbia_workspace_packet",
        browseract_names=("BrowserAct", "Nonverbia"),
        aliases=("nonverbia", "nonverbia_workspace", "inspect_nonverbia_workspace"),
        template_key="nonverbia_workspace_reader",
        page_input_name="page_url",
    ),
    _template_reader_service(
        service_key="documentation_ai_workspace_reader",
        capability_key="documentation_ai_workspace_reader",
        tool_name="browseract.documentation_ai_workspace_reader",
        skill_key="inspect_documentation_ai_workspace",
        task_key="inspect_documentation_ai_workspace",
        name="Inspect Documentation.AI Workspace",
        description="Template-backed BrowserAct Documentation.AI workspace reader for doc-generation surface discovery, prompt capture, and output inspection.",
        deliverable_type="documentation_ai_workspace_packet",
        browseract_names=("BrowserAct", "Documentation.AI"),
        aliases=("documentation_ai", "documentation_ai_workspace", "inspect_documentation_ai_workspace"),
        template_key="documentation_ai_workspace_reader",
        page_input_name="page_url",
    ),
    _template_reader_service(
        service_key="invoiless_workspace_reader",
        capability_key="invoiless_workspace_reader",
        tool_name="browseract.invoiless_workspace_reader",
        skill_key="inspect_invoiless_workspace",
        task_key="inspect_invoiless_workspace",
        name="Inspect Invoiless Workspace",
        description="Template-backed BrowserAct Invoiless workspace reader for invoice dashboard capture, draft inspection, and operator state snapshots.",
        deliverable_type="invoiless_workspace_packet",
        browseract_names=("BrowserAct", "Invoiless"),
        aliases=("invoiless", "invoiless_workspace", "inspect_invoiless_workspace"),
        template_key="invoiless_workspace_reader",
        page_input_name="page_url",
    ),
    _template_reader_service(
        service_key="markupgo_workspace_reader",
        capability_key="markupgo_workspace_reader",
        tool_name="browseract.markupgo_workspace_reader",
        skill_key="inspect_markupgo_workspace",
        task_key="inspect_markupgo_workspace",
        name="Inspect MarkupGo Workspace",
        description="Template-backed BrowserAct MarkupGo workspace reader for markup, preview, and output-state capture when the UI lane matters more than the legacy API shortcut.",
        deliverable_type="markupgo_workspace_packet",
        browseract_names=("BrowserAct", "MarkupGo"),
        aliases=("markupgo", "markupgo_workspace", "inspect_markupgo_workspace"),
        template_key="markupgo_workspace_reader",
        page_input_name="page_url",
    ),
    _template_reader_service(
        service_key="paperguide_workspace_reader",
        capability_key="paperguide_workspace_reader",
        tool_name="browseract.paperguide_workspace_reader",
        skill_key="inspect_paperguide_workspace",
        task_key="inspect_paperguide_workspace",
        name="Inspect Paperguide Workspace",
        description="Template-backed BrowserAct Paperguide workspace reader for research surfaces, note capture, and citation-state inspection.",
        deliverable_type="paperguide_workspace_packet",
        browseract_names=("BrowserAct", "Paperguide"),
        aliases=("paperguide", "paperguide_workspace", "inspect_paperguide_workspace"),
        template_key="paperguide_workspace_reader",
        page_input_name="page_url",
    ),
    _template_reader_service(
        service_key="apixdrive_workspace_reader",
        capability_key="apixdrive_workspace_reader",
        tool_name="browseract.apixdrive_workspace_reader",
        skill_key="inspect_apixdrive_workspace",
        task_key="inspect_apixdrive_workspace",
        name="Inspect ApiX-Drive Workspace",
        description="Template-backed BrowserAct ApiX-Drive workspace reader for connector, flow, and automation-state capture.",
        deliverable_type="apixdrive_workspace_packet",
        browseract_names=("BrowserAct", "ApiX-Drive"),
        aliases=("apixdrive", "api_x_drive", "apix_drive", "inspect_apixdrive_workspace"),
        template_key="apixdrive_workspace_reader",
        page_input_name="page_url",
    ),
    _template_reader_service(
        service_key="peekshot_workspace_reader",
        capability_key="peekshot_workspace_reader",
        tool_name="browseract.peekshot_workspace_reader",
        skill_key="inspect_peekshot_workspace",
        task_key="inspect_peekshot_workspace",
        name="Inspect PeekShot Workspace",
        description="Template-backed BrowserAct PeekShot workspace reader for preview capture, screenshot-state inspection, and UI option discovery.",
        deliverable_type="peekshot_workspace_packet",
        browseract_names=("BrowserAct", "PeekShot"),
        aliases=("peekshot", "peekshot_workspace", "inspect_peekshot_workspace"),
        template_key="peekshot_workspace_reader",
        page_input_name="page_url",
    ),
    _template_reader_service(
        service_key="unmixr_workspace_reader",
        capability_key="unmixr_workspace_reader",
        tool_name="browseract.unmixr_workspace_reader",
        skill_key="inspect_unmixr_workspace",
        task_key="inspect_unmixr_workspace",
        name="Inspect Unmixr AI Workspace",
        description="Template-backed BrowserAct Unmixr AI workspace reader for voice, content, and media generation surface discovery.",
        deliverable_type="unmixr_workspace_packet",
        browseract_names=("BrowserAct", "Unmixr AI"),
        aliases=("unmixr", "unmixr_ai", "unmixr_workspace", "inspect_unmixr_workspace"),
        template_key="unmixr_workspace_reader",
        page_input_name="page_url",
    ),
    _template_reader_service(
        service_key="vizologi_workspace_reader",
        capability_key="vizologi_workspace_reader",
        tool_name="browseract.vizologi_workspace_reader",
        skill_key="inspect_vizologi_workspace",
        task_key="inspect_vizologi_workspace",
        name="Inspect Vizologi Workspace",
        description="Template-backed BrowserAct Vizologi workspace reader for strategy-canvas capture, market-research inspection, and operator snapshots.",
        deliverable_type="vizologi_workspace_packet",
        browseract_names=("BrowserAct", "Vizologi"),
        aliases=("vizologi", "vizologi_workspace", "inspect_vizologi_workspace"),
        template_key="vizologi_workspace_reader",
        page_input_name="page_url",
    ),
)


def browseract_ui_service_definitions() -> tuple[BrowserActUiServiceDefinition, ...]:
    return _SERVICE_DEFINITIONS


def browseract_ui_service_by_capability(capability_key: str) -> BrowserActUiServiceDefinition | None:
    normalized = str(capability_key or "").strip().lower()
    for service in _SERVICE_DEFINITIONS:
        if normalized == service.capability_key:
            return service
    return None


def browseract_ui_service_by_service_key(service_key: str) -> BrowserActUiServiceDefinition | None:
    normalized = str(service_key or "").strip().lower()
    for service in _SERVICE_DEFINITIONS:
        if normalized == service.service_key:
            return service
    return None


def browseract_ui_service_by_tool(tool_name: str) -> BrowserActUiServiceDefinition | None:
    normalized = str(tool_name or "").strip().lower()
    for service in _SERVICE_DEFINITIONS:
        if normalized == service.tool_name:
            return service
    return None
