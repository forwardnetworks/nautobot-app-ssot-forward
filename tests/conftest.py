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


@pytest.fixture(autouse=True)
def _fresh_sync_baseline():
    """Give each test the clean profile table an in-memory database would.

    A run records the snapshot it synced on the saved profile, and the next run
    with the same snapshot is skipped as unchanged. That is correct behaviour in
    production and a trap in a shared database: two tests using the same profile
    and snapshot pass alone and the second fails in sequence, as the plan it
    expected to build is skipped before it starts. An in-memory database hides
    this because it is rebuilt per process; the container stack does not.

    Only touches the database when one is available; a bare environment is a
    no-op.
    """
    try:
        from django.apps import apps
        from django.db import connection

        if not apps.ready or connection.settings_dict.get("NAME") in (None, ""):
            yield
            return
        from forward_nautobot.models import ForwardConnectionProfile

        # Match what an in-memory database gives every test: no saved profiles
        # from a previous test. Some tests assert that none exists.
        ForwardConnectionProfile.objects.all().delete()
    except Exception:
        pass
    yield
