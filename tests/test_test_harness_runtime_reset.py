from __future__ import annotations

import pytest

from tests import conftest as suite_conftest


class _JoinRaceThread:
    def __init__(self, errors: list[RuntimeError | None]) -> None:
        self.errors = list(errors)
        self.join_timeouts: list[float | None] = []

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        error = self.errors.pop(0) if self.errors else None
        if error is not None:
            raise error


def test_memorial_thread_reset_retries_join_before_start_race() -> None:
    thread = _JoinRaceThread(
        [RuntimeError(suite_conftest._THREAD_JOIN_BEFORE_START_ERROR), None]
    )

    suite_conftest._join_memorial_thread(thread, timeout_seconds=0.05)  # type: ignore[arg-type]

    assert len(thread.join_timeouts) == 2
    assert all(timeout is not None and 0 < timeout <= 0.05 for timeout in thread.join_timeouts)


def test_memorial_thread_reset_propagates_other_join_failures() -> None:
    thread = _JoinRaceThread([RuntimeError("cannot join current thread")])

    with pytest.raises(RuntimeError, match="cannot join current thread"):
        suite_conftest._join_memorial_thread(thread, timeout_seconds=0.05)  # type: ignore[arg-type]
