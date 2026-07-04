from __future__ import annotations

import os

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Release gate: skipped non-integration tests are not acceptable."""
    if not os.getenv("FORWARD_STRICT_NO_SKIPS"):
        return
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = getattr(terminal, "stats", {}).get("skipped", ()) if terminal else ()
    if skipped:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
