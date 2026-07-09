"""Pytest bootstrap.

When ``DJANGO_SETTINGS_MODULE`` is set (the container test stack sets it to
``nautobot_config``), configure Django up front so the plugin's Nautobot-backed
modules import — which flips ``CONTRIB_AVAILABLE`` on and lets the contrib / REST
API tests run in-process. When it is not set (plain local shell, CI without a
Nautobot install) this is a no-op and those tests skip exactly as before.
"""

from __future__ import annotations

import os


def _maybe_setup_django() -> None:
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        return
    try:
        # nautobot.setup() loads the plugin list into INSTALLED_APPS (a bare
        # django.setup() does not), which the plugin's Django model needs to
        # register its app_label.
        import nautobot

        nautobot.setup()
    except Exception:  # pragma: no cover - fall back / no Nautobot available
        try:
            import django

            django.setup()
        except Exception:
            pass


_maybe_setup_django()
