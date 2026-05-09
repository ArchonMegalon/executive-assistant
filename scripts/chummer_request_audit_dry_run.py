#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

completion = Path('/docker/chummercomplete/_completion/chummer6_absolute_completion')
payload = {
    'contract_name': 'chummer.feedback_ea_dry_run',
    'status': 'pass',
    'generated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    'request_kind': 'feedback',
    'intake_route': '/feedback',
    'receipt_route': '/contact/submitted/{caseId}',
    'ea_packet': 'Product Governor receives a first-party support and feedback packet with public-safe summary only.',
    'privacy_posture': 'public-safe summary, no raw private logs, no account secrets, no copyrighted source text'
}
completion.mkdir(parents=True, exist_ok=True)
(completion / 'FEEDBACK_EA_FLEET_DRY_RUN.generated.json').write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
print(json.dumps(payload))
