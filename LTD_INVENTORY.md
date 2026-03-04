# EA LTD Inventory (Auditor Reference)

Last updated: 2026-03-04  
Scope: Operator-declared lifetime deals (LTDs) and plan tiers currently tracked for EA OS.

## Notes
- This file is the single auditor-facing inventory for external LTD tooling.
- Tiers are recorded exactly as provided by the operator in project feedback.
- If a tier is unknown/unverified, it is explicitly marked.
- Capability keys map to `ea/app/skills/capability_registry.py`.

## Inventory

| Product | Tier / Plan | Capability key(s) | EA OS role | Tier status |
|---|---|---|---|---|
| AppSumo Plus | Plus membership | n/a | Procurement channel (not runtime capability) | Declared |
| BrowserAct | Tier 5 | `browseract` | Browser automation ingress and event enrichment | Declared |
| MetaSurvey | 4 codes | `metasurvey` | Structured intake and feedback collection | Declared |
| Vizologi | Tier 4 | `vizologi` | Secondary research and strategy support | Declared |
| PeekShot | Tier 3 | `peekshot` | Multimodal support asset generation | Declared |
| Paperguide | Tier 4 | `paperguide` | Secondary research support | Declared |
| ApproveThis | Tier 3 | `approvethis` | Approval routing and typed-safe-action support | Declared |
| AvoMap | Tier 10 | `avomap` | Travel route/video sidecar and trip context support | Declared |
| Prompting.Systems | Tier not specified | `prompting_systems` | Prompt pack compilation | Unspecified tier |
| Undetectable / Humanizer AI | Tier not specified | `undetectable` | Tone polishing for approved outbound copy | Unspecified tier |
| ApiX-Drive | Highest tier | `apix_drive` | External event/action bridge via connectors/webhooks | Declared |
| Involvness (assumed involve.me) | Tier not verified | `involve_me` | Guided external intake front-end | Assumed product |
| OneAir Elite | Elite | `oneair` | Travel savings/reprice optimization | Declared |
| Magix AI / AI Magicx | Highest tier | `ai_magicx` | Secondary AI workbench / multimodal support | Declared |
| 1minAI | Highest tier | `one_min_ai` | Multimodal burst support | Declared |

## Auditor checks
- Verify every capability key above exists in `CAPABILITY_REGISTRY`.
- Verify skill routing uses capability keys only (vendor access through skills/contracts).
- Verify unknown/assumed entries are resolved before production-critical usage.
