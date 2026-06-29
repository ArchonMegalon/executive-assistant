---
name: ea-browser-ooda-operator
description: Generic governed OODA browser operator for logging into arbitrary websites with user-provided or EA-stored credentials, using remembered user context, performing reversible website tasks such as search, comparison, carts, unsent drafts, account forms, support requests, or booking candidates, and stopping before purchases, bookings, sends, cancellations, posts, payments, or commitments. Use when Codex/EA must operate a real website as a paid human assistant would, especially for credentialed web tasks, carts, drafts, checkout boundaries, Cloudflare/anti-bot handoff, screenshots, resumable receipts, or action-required-only Telegram updates.
---

# EA Browser OODA Operator

Use this skill for website work where EA should behave like a careful human assistant: log in, orient against the user's task and context, do reversible work, and return a decision-ready result or a precise handoff.

## Operating Contract

1. Define the task as an OODA packet:
   - Observe: target site, account identity, requested outcome, item/action list, deadlines, constraints.
   - Orient: user context, location, budget, preferences, substitutions, prior shortlist, account state, irreversible boundaries.
   - Decide: exact reversible actions to perform, success proof, notification policy, and explicit stop conditions.
   - Act: browser steps only until the stop condition or a blocker is reached.
2. Treat credentials as scoped secrets. Use user-provided credentials only for the named site/task. Do not print passwords, store new secrets, or reuse them for other domains unless the user explicitly asks.
3. Default to reversible actions only:
   - Allowed: log in, search, compare, fill forms that remain unsent, add/remove cart items, save drafts, collect links, stage booking candidates, update local receipts.
   - Requires explicit approval immediately before execution: purchase, payment, booking, cancellation, sending external messages, posting, signing, committing, or changing account/security settings.
4. Verify account context before acting. If the visible account identity does not match the requested account, stop and report the mismatch.
5. Preserve user context. Apply known location, family/preferences, product substitutions, budget, and "bonus" constraints when they are relevant.
6. Be quiet unless the user needs to act. Do not send progress noise for ordinary internal search, ranking, or retries; notify only for approval, a completed review surface, or a real blocker.
7. Produce a receipt. Include site, account hash or email domain only when safe, task summary, actions attempted, items staged, cart/draft/booking status, total if visible, URLs, timestamps, context used, and blockers. Do not include raw passwords or payment data.

## Generic Website Task Model

Normalize every request into one or more of these reversible work types before browsing:

- `research`: search a site or open web, compare candidates, validate contact/product fit, collect links.
- `cart`: log in, find suitable items, add/remove basket items, stop at cart or checkout review.
- `draft`: write an unsent message, email, support request, contact form, or account note, stop before send/submit.
- `booking_candidate`: find dates/slots/options, prefill reversible details only, stop before booking or payment.
- `account_review`: inspect account state, subscriptions, orders, invoices, settings, or support status without changing security/payment settings.
- `handoff`: preserve an authenticated browser state or receipt when a challenge, MFA, or site restriction needs the user.

For multi-site tasks, handle each site as its own OODA subpacket and produce one merged recommendation only after the final review surfaces are checked.

## Context And Quality Gate

Before acting on a website:

1. Load applicable EA context if available: user location, delivery country, contact details, family/member names, language preference, budget, substitutions, and prior decisions.
2. Restate only the operational constraints internally; do not expose private memory unless needed for the receipt.
3. Reject or downrank candidates that do not match the task class, geography, legal domain, or requested recipient.
4. Audit the chosen candidate before staging it:
   - product tasks: item is buyable, fits constraints, quantity is correct, price/discount is visible where possible.
   - service tasks: provider is in the right area and profession, has a plausible contact path, and matches the actual request.
   - draft tasks: recipient and body match the user's intent, not just the literal transcript text.
5. If the audit fails, keep searching or stop with a blocker. Do not stage nonsense just to produce an output.

## Browser Procedure

1. Prefer an existing EA browser/runtime path over ad hoc scripts:
   - Use an existing app/browser connector if available.
   - Use local Playwright only when the site works from the current environment.
   - Use a persistent/session profile when a task must survive handoff.
2. Start with a warm navigation to the public site, accept cookies if needed, and wait for ordinary security checks.
3. Log in with the scoped account. Verify success by account menu, profile page, or lack of login error.
4. Execute the reversible task list item by item. After each item/action, check visible confirmation.
5. Navigate to the final review surface: cart, draft list, comparison page, booking summary, or account page.
6. Stop before irreversible controls. Do not click checkout payment, "place order", "send", "book", "cancel", "submit application", or equivalent final actions.
7. Save enough proof for resumption: final URL, visible status text, staged item labels, totals, and screenshots when useful.

## Anti-Bot And Handoff

Do not bypass security challenges. If Cloudflare, CAPTCHA, MFA, device verification, email code, app approval, or human interaction is required:

1. Keep the browser/session alive if possible.
2. Ask only for the minimum user action: "Please clear the Cloudflare check in this browser" or "Please provide the one-time code."
3. Resume from the cleared/authenticated session.
4. If the current environment cannot expose an interactive browser, stop with a handoff receipt instead of retrying noisy automation.

For receipt fields and blocker labels, read [receipt-contract.md](references/receipt-contract.md).

## Quality Bar

- Do not rely on page titles alone; inspect visible body text or DOM state.
- Do not claim an item is in a cart/draft unless the final review surface proves it.
- If an exact product is unavailable, use allowed substitutions only when the user permits them, and record the substitution.
- If a site blocks automation, report the concrete blocker and next human action. Do not invent success.
- For Telegram delivery, send one compact message only when the user must decide, approve, clear a challenge, or review a completed cart/draft/booking candidate.
