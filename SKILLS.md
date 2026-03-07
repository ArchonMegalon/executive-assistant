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

## Initial Catalog

| Skill | Backing Task | Deliverable | Workflow | Memory Reads | Memory Writes | Human / Approval Notes | Suggested Providers |
|---|---|---|---|---|---|---|---|
| `inbox_triage` | `inbox_triage` | `inbox_triage_report` | `artifact_then_packs` | `stakeholders`, `communication_policies`, `commitments`, `interruption_budgets` | `follow_up_rules`, `stakeholder_follow_up_fact` | Human review for risky external replies; approval before `connector.dispatch` | `1min.AI`, `AI Magicx`, `Teable`, `ApproveThis` |
| `stakeholder_briefing` | `stakeholder_briefing` | `stakeholder_briefing` | `artifact_then_memory_candidate` | `stakeholders`, `relationships`, `commitments`, `decision_windows` | `stakeholder_briefing_fact` | Operator review for high-sensitivity stakeholders | `BrowserAct`, `PeekShot`, `Paperguide`, `MarkupGo` |
| `meeting_prep` | `meeting_prep` | `meeting_pack` | `artifact_then_memory_candidate` | `stakeholders`, `commitments`, `deadline_windows`, `decision_windows` | `meeting_pack_fact` | Human review for executive-facing packs | `BrowserAct`, `Paperguide`, `MarkupGo` |
| `external_send` | `external_send` | `draft_message` | `artifact_then_dispatch` | `communication_policies`, `delivery_preferences`, `authority_bindings` | `stakeholder_follow_up_fact` | Approval-backed send; optional human review before dispatch | `ApproveThis`, `ApiX-Drive`, `MarkupGo` |
| `follow_up_enforcement` | `follow_up_enforcement` | `follow_up_bundle` | `artifact_then_dispatch_then_memory_candidate` | `commitments`, `follow_ups`, `follow_up_rules`, `deadline_windows` | `follow_up_fact` | Human escalation when SLA or authority rules require it | `Teable`, `ApiX-Drive`, `ApproveThis` |
| `travel_ops` | `travel_ops` | `travel_itinerary` | `artifact_then_dispatch` | `delivery_preferences`, `interruption_budgets`, `authority_bindings` | `travel_follow_up_fact` | Approval for bookings and cost-sensitive changes | `OneAir`, `MarkupGo`, `ApproveThis` |
| `research_decision_memo` | `research_decision_memo` | `decision_summary` | `artifact_then_memory_candidate` | `decision_windows`, `stakeholders`, `relationships` | `decision_research_fact` | Human review for high-stakes decisions | `Paperguide`, `Vizologi`, `ChatPlayground AI` |
| `documentation_freshness` | `documentation_freshness` | `documentation_refresh_packet` | `tool_then_artifact` | `entities`, `relationships`, `communication_policies` | `documentation_freshness_fact` | Human review before publishing docs or runbook changes | `Documentation.AI`, `AI Magicx` |

## Notes

- External providers are capability hints, not the source of truth. EA keeps Postgres as the runtime and memory system of record.
- `Teable` belongs on the operator cockpit side, not in the core execution ledger.
- `ApproveThis` is the external approval edge, not the internal policy engine.
- `ChatPlayground AI` and `Prompting Systems` are evaluation and prompt-authoring tools, not the live planner brain.
