"""Load the pinned guard in the CLI and its automatically launched daemon.

Only the isolated Origin image adds this directory to PYTHONPATH. Python normally
ignores sitecustomize failures, which would silently run an unguarded daemon;
fail closed instead, without printing environment or vendor exception details.
"""
import os

try:
    from scripts.origin_browseract_guard import install
    install()
except BaseException:
    os.write(2, b"origin_browseract_lifecycle_guard_unavailable\n")
    os._exit(78)
