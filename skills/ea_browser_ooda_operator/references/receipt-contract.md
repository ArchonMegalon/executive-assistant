# Browser OODA Receipt Contract

Use these fields when reporting or storing browser work receipts.

## Core Fields

- `site`: canonical host, for example `pagro.at`
- `account_ref`: visible account email when user-safe, otherwise a hash or account label
- `work_type`: one of `research`, `cart`, `draft`, `booking_candidate`, `account_review`, or `handoff`
- `task_summary`: one sentence
- `requested_actions`: normalized reversible action list
- `completed_actions`: actions proven on the site
- `context_used`: short list of non-secret user context applied, for example `location:1200 Wien` or `prefers_superhero_bonus`
- `quality_gate`: pass/fail plus a short reason for candidate fit, geography, recipient, and task alignment
- `staged_items`: cart/draft/booking candidates with labels, quantities, and visible prices when available
- `final_surface_url`: cart, draft, booking summary, or review URL
- `total_visible`: visible cart/order total before checkout, if available
- `notification_policy`: usually `action_required_only`
- `stop_condition`: why the browser stopped
- `irreversible_actions_attempted`: must be empty unless the user explicitly approved that action
- `blockers`: list of blocker codes
- `evidence`: screenshot paths, visible text excerpts, or hashes; never raw passwords/payment data

## Stop Conditions

- `cart_ready_for_user_review`
- `draft_ready_for_user_review`
- `booking_candidate_ready_for_user_review`
- `comparison_ready_for_user_decision`
- `account_review_ready_for_user_decision`
- `human_challenge_required`
- `mfa_required`
- `account_mismatch`
- `item_unavailable`
- `site_blocked_automation`
- `approval_required_before_irreversible_action`
- `quality_gate_failed`

## Blocker Codes

- `cloudflare_not_cleared`
- `captcha_required`
- `mfa_code_required`
- `login_failed`
- `login_form_not_found`
- `account_context_mismatch`
- `cart_confirmation_missing`
- `draft_confirmation_missing`
- `candidate_quality_failed`
- `wrong_geography_or_profession`
- `checkout_boundary_reached`
- `send_submit_boundary_reached`
- `site_unreachable`
- `browser_runtime_unavailable`
