from __future__ import annotations

import importlib
import os

import pytest


def _configure_nautobot_test_apps() -> None:
    """Mirror nautobot-server's plugin-loading step for plain pytest runs."""
    if not os.getenv("NAUTOBOT_DB_HOST"):
        os.environ.setdefault("NAUTOBOT_DB_NAME", ":memory:")
    try:
        import django
        from django.apps import apps
        from django.conf import settings
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        from nautobot.extras.plugins.utils import load_plugins
    except ModuleNotFoundError:
        return
    if apps.ready:
        return
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nautobot_config")
    settings_module = importlib.import_module(os.environ["DJANGO_SETTINGS_MODULE"])
    load_plugins(settings_module)
    django.setup()
    if settings.DATABASES["default"]["NAME"] == ":memory:":
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes("forward_nautobot"))


_configure_nautobot_test_apps()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Release gate: skipped non-integration tests are not acceptable."""
    if not os.getenv("FORWARD_STRICT_NO_SKIPS"):
        return
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = getattr(terminal, "stats", {}).get("skipped", ()) if terminal else ()
    if skipped:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
