# Skill Catalog

This repository now treats executive capabilities as first-class skills layered on top of the durable runtime kernel. A skill is a product-facing contract that binds together:

- a `skill_key`
- a backing `task_key`
- a workflow template / planner shape
- memory reads and writes
- authority and review posture
- allowed tools and human roles
- input/output schemas
- evaluation cases

The API surface for this layer is `POST /v1/skills`, `GET /v1/skills`, and `GET /v1/skills/{skill_key}`. Skills persist through the existing task-contract store, so the runtime stays schema-light while the product layer becomes explicit. The same API now also carries `provider_hints_json`, so the LTD-backed service stack is projected into the product skill layer instead of living only in markdown notes. `GET /v1/skills?provider_hint=BrowserAct` (or another provider name) filters the catalog against those hints.

Under the runtime surface, EA now also projects typed read records instead of making every caller re-interpret storage blobs:

- `TaskContractPolicyRecord` for compiled contract policy
- `SkillCatalogRecord` for product-facing skill metadata
- `ProviderBindingState` for provider auth/config/executable posture

## Initial Catalog

| Skill | Backing Task | Deliverable | Workflow | Memory Reads | Memory Writes | Human / Approval Notes | Suggested Providers |
|---|---|---|---|---|---|---|---|
| `inbox_triage` | `inbox_triage` | `inbox_triage_report` | `artifact_then_packs` | `stakeholders`, `communication_policies`, `commitments`, `interruption_budgets` | `follow_up_rules`, `stakeholder_follow_up_fact` | Human review for risky external replies; approval before `connector.dispatch` | `1min.AI`, `AI Magicx`, `Teable`, `ApproveThis` |
| `stakeholder_briefing` | `stakeholder_briefing` | `stakeholder_briefing` | `artifact_then_memory_candidate` | `stakeholders`, `relationships`, `commitments`, `decision_windows` | `stakeholder_briefing_fact` | Operator review for high-sensitivity stakeholders | `BrowserAct`, `PeekShot`, `Paperguide`, `MarkupGo` |
| `meeting_prep` | `meeting_prep` | `meeting_pack` | `artifact_then_memory_candidate` | `stakeholders`, `commitments`, `deadline_windows`, `decision_windows` | `meeting_pack_fact` | Human review for executive-facing packs | `BrowserAct`, `Paperguide`, `MarkupGo` |
| `ltd_inventory_refresh` | `ltd_inventory_refresh` | `ltd_inventory_profile` | `tool_then_artifact` | `account_inventory` |  | BrowserAct-backed observation only; no approval required for discovery-only refresh | `BrowserAct`, `Teable`, `MarkupGo` |
| `browseract_bootstrap_manager` | `browseract_bootstrap_manager` | `browseract_workflow_spec_packet` | `tool_then_artifact` | `entities`, `relationships` |  | Draft-only BrowserAct workflow-spec builder for prompt-tool and page-extract templates; operator review stays available for architect packets | `BrowserAct` |
| `browseract_workflow_repair_manager` | `browseract_workflow_repair_manager` | `browseract_workflow_repair_packet` | `tool_then_artifact` | `entities`, `relationships` |  | Draft-only BrowserAct workflow repair lane; Gemini Vortex patches broken spec packets without sending them through Codex | `BrowserAct`, `Gemini Vortex` |
| `external_send` | `external_send` | `draft_message` | `artifact_then_dispatch` | `communication_policies`, `delivery_preferences`, `authority_bindings` | `stakeholder_follow_up_fact` | Approval-backed send; optional human review before dispatch | `ApproveThis`, `ApiX-Drive`, `MarkupGo` |
| `follow_up_enforcement` | `follow_up_enforcement` | `follow_up_bundle` | `artifact_then_dispatch_then_memory_candidate` | `commitments`, `follow_ups`, `follow_up_rules`, `deadline_windows` | `follow_up_fact` | Human escalation when SLA or authority rules require it | `Teable`, `ApiX-Drive`, `ApproveThis` |
| `travel_ops` | `travel_ops` | `travel_itinerary` | `artifact_then_dispatch` | `delivery_preferences`, `interruption_budgets`, `authority_bindings` | `travel_follow_up_fact` | Approval for bookings and cost-sensitive changes | `OneAir`, `MarkupGo`, `ApproveThis` |
| `research_decision_memo` | `research_decision_memo` | `decision_summary` | `artifact_then_memory_candidate` | `decision_windows`, `stakeholders`, `relationships` | `decision_research_fact` | Human review for high-stakes decisions | `Paperguide`, `Vizologi`, `ChatPlayground AI` |
| `design_petition` | `design_petition` | `design_petition_packet` | `artifact_then_memory_candidate` | `design_scope`, `contract_sets`, `feedback_findings` | `design_petition_fact` | Lead-designer review before design canon changes; blocked-by-design escalation lane | `ChatPlayground AI`, `Gemini Vortex` |
| `design_synthesis` | `design_synthesis` | `design_synthesis_packet` | `artifact_then_memory_candidate` | `design_scope`, `feedback_findings`, `public_status` | `design_synthesis_fact` | Lead-designer review for clustered audit/feedback reduction | `Gemini Vortex`, `ChatPlayground AI` |
| `mirror_status_brief` | `mirror_status_brief` | `mirror_status_brief` | `rewrite` | `design_scope` |  | Short parity-summary lane for designers; no memory write | `ChatPlayground AI` |
| `documentation_freshness` | `documentation_freshness` | `documentation_refresh_packet` | `tool_then_artifact` | `entities`, `relationships`, `communication_policies` | `documentation_freshness_fact` | Human review before publishing docs or runbook changes | `Documentation.AI`, `AI Magicx` |
| `chummer6_public_writer` | `chummer6_public_copy_refresh` | `chummer6_guide_refresh_packet` | `tool_then_artifact` | `entities`, `relationships`, `repo_readmes`, `design_scope`, `public_status` | `chummer6_public_copy_fact` | Operator review for public-guide copy and audience translation; Gemini Vortex owns the reader-safe writing lane so public pages stop sounding like maintainers writing memos to themselves | `Gemini Vortex`, `Prompting Systems`, `BrowserAct` |
| `chummer6_public_auditor` | `chummer6_public_copy_audit` | `chummer6_guide_refresh_packet` | `tool_then_artifact` | `entities`, `relationships`, `repo_readmes`, `design_scope`, `public_status` | `chummer6_public_audit_fact` | Editorial self-audit lane before image work; rejects maintainer-speak drift and misrouted calls-to-action | `Gemini Vortex`, `Prompting Systems`, `BrowserAct` |
| `chummer6_visual_director` | `chummer6_guide_refresh` | `chummer6_guide_refresh_packet` | `tool_then_artifact` | `entities`, `relationships`, `repo_readmes`, `design_scope`, `public_status` | `chummer6_style_epoch`, `chummer6_scene_ledger`, `chummer6_visual_critic_fact` | Operator review for public-guide image direction; Gemini Vortex is the planner brain, style epochs keep each full pass coherent, and the scene ledger exists to stop another repo-wide table-huddle relapse | `Gemini Vortex`, `AI Magicx`, `Prompting Systems`, `BrowserAct` |
| `chummer6_scene_auditor` | `chummer6_scene_plan_audit` | `chummer6_guide_refresh_packet` | `tool_then_artifact` | `entities`, `relationships`, `repo_readmes`, `design_scope`, `public_status` | `chummer6_scene_audit_fact` | Scene-plan QA lane before rendering; enforces composition diversity and page-role fit | `Gemini Vortex`, `Prompting Systems`, `BrowserAct` |
| `chummer6_visual_auditor` | `chummer6_visual_audit` | `chummer6_guide_refresh_packet` | `tool_then_artifact` | `entities`, `relationships`, `repo_readmes`, `design_scope`, `public_status` | `chummer6_visual_audit_fact` | Post-render QA lane; rejects placeholder vibes and catches repetition before publish | `Gemini Vortex`, `AI Magicx`, `Prompting Systems`, `BrowserAct` |
| `chummer6_pack_auditor` | `chummer6_pack_audit` | `chummer6_guide_refresh_packet` | `tool_then_artifact` | `entities`, `relationships`, `repo_readmes`, `design_scope`, `public_status` | `chummer6_pack_audit_fact` | Whole-pack audit lane; checks editorial drift, style-epoch coherence, and publish readiness | `Gemini Vortex`, `BrowserAct` |

## Notes

- External providers are capability hints, not the source of truth. EA keeps Postgres as the runtime and memory system of record.
- `Teable` belongs on the operator cockpit side, not in the core execution ledger.
- `ApproveThis` is the external approval edge, not the internal policy engine.
- `ChatPlayground AI` and `Prompting Systems` are evaluation and prompt-authoring tools, not the live planner brain; `Gemini Vortex` owns the primary structured-generation lane for both `chummer6_public_writer` and `chummer6_visual_director`, while downstream helpers stay bounded to refinement/render work.
- `chummer6_public_writer` exists so audience translation and public-action routing are explicit skill policy instead of accidental prompt seasoning.
- `chummer6_visual_director` now writes a reviewed style epoch and scene-ledger memory trail so one full regeneration pass can share a visual family without letting every page collapse into the same shot.
- The current `chummer6_guide_worker.py` generation path is `chummer6_public_writer` -> `chummer6_visual_director` -> local scene/editorial pack audits. The four auditor skills (`chummer6_public_auditor`, `chummer6_scene_auditor`, `chummer6_visual_auditor`, `chummer6_pack_auditor`) are explicit QA lanes in the catalog, but they are not silently auto-invoked by the default worker run.
- After the creative pack is accepted, `scripts/chummer6_release_builder.py` is the deterministic tail that normalizes the current desktop downloads manifest into a guide-facing release matrix; it is intentionally a boring build artifact stage, not another AI writer lane.
- `browseract_bootstrap_manager` is now a real first-class skill, not just a helper script with stage fright.
- `browseract_workflow_repair_manager` is the companion self-heal lane for when a BrowserAct workflow decides that typing `/text` literally is somehow a personality.
- `design_petition`, `design_synthesis`, and `mirror_status_brief` exist so blocked-by-design escalation, repeated-finding clustering, and mirror-status summarization become explicit runtime lanes instead of more markdown sprawl.
- `python3 scripts/generate_browseract_content_templates.py` uses the BrowserAct bootstrap skill to emit ready-to-edit packet and workflow JSON for Economist, Atlantic, NYTimes, ApproveThis, and MetaSurvey reader templates in `/mnt/pcloud/EA/browseract_templates`.
