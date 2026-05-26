# Black Ledger Map Interaction Spec

## Interactions

- hover/focus district: highlight polygon and update panel
- hover/focus event: update panel with event summary and linked receipt/dispatch
- click district: jump to list fallback card
- click replay step: navigate to the selected turn route
- click mode: change visual emphasis without hiding the list fallback

## Accessibility

- keyboard focus reaches districts, events, mode buttons, and replay controls
- list fallback mirrors map content
- reduced motion removes looping pulse/arc motion
- color is never the only signal

## Motion

Meaningful motion only:

- pulsing hotspots for active/new events
- dashed arc flow for pressure movement
- no decorative idle animation outside those signals
