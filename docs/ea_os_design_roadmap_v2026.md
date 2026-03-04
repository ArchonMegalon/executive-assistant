# EA OS Design Roadmap v2026

Date: 2026-03-04  
Scope: design sequence after v1.12.7 contract freeze

## Strategy
Consolidation before expansion:
1. Freeze control-plane contracts in 12.x.
2. Expand capabilities on top of those contracts.

## Phases

### Phase 0: v1.12.7 Contract Freeze
- Freeze LLM gateway, repair, Telegram safety boundaries.
- Separate scheduler, poller, and interaction responsibilities.

### Phase 1: v1.13 Profile Intelligence Core
- Build layered person profiles (stable, situational, learned, confidence).
- Introduce dossier contracts and deterministic critical-action lane before normal compose.
- Keep person profiles isolated and enforce household graph sharing policies explicitly.

### Phase 2: v1.14 Trust + Epics
- Introduce long-running thread/epic objects.
- Strengthen replay/dead-letter/trust flows.
- Add deterministic epic ranking + delta summaries in briefing compose.
- Track unresolved epic state and include epic salience in mode selection.

### Phase 3: v1.15 Document Intelligence
- Safe retrieval packs and ownership-aware document signals.
- Keep fail-closed behavior for ambiguous ownership.

### Phase 4: v1.16 Typed Safe Actions
- Promote staged actions into typed, approval-gated workflows.

### Phase 5: v1.17 Personalization
- Preference learning at concept/source/epic level.

### Phase 6: v1.18 Planner + Runtime Alignment
- Shift from reactive loop to proactive precompute/planning loop.

### Phase 7: v1.19 Future Intelligence Care OS
- Promote commitment-protection behavior into first-class runtime contracts.
- Prioritize high-exposure commitments + risk intersections before generic summarize/ranking paths.
- Enforce confidence-aware composition and bounded preparation planning through smoke + real milestone gates.

## Execution Rule
No new feature wave ships without an explicit contract owner and smoke test
coverage for boundary invariants.
