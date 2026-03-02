from __future__ import annotations

import importlib
import os
import sys

ROOT = os.environ.get('EA_PYTHONPATH_ROOT')
if ROOT:
    sys.path.insert(0, ROOT)

from app.telegram.safety import (  # noqa: E402
    SAFE_PLACEHOLDER_COPY,
    SAFE_SIMPLIFIED_COPY,
    detect_forbidden_pattern,
    sanitize_telegram_text,
)

assert detect_forbidden_pattern('{"error": {"message": "template_id invalid"}}') in {'json_block', 'template_id'}
assert sanitize_telegram_text('{"error": {"message": "template_id invalid"}}') == SAFE_SIMPLIFIED_COPY
assert sanitize_telegram_text('Traceback (most recent call last):\nNameError: boom') == SAFE_SIMPLIFIED_COPY
assert sanitize_telegram_text(SAFE_PLACEHOLDER_COPY, placeholder=True) == SAFE_PLACEHOLDER_COPY

# Import the safety module explicitly.
importlib.import_module('app.telegram.safety')
print('SMOKE_OK safety module')
