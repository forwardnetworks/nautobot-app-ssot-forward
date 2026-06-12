"""Portable Nautobot settings for local tests and a lightweight dev server."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from nautobot.core.settings import *  # noqa: F401,F403
    from nautobot.core.settings_funcs import is_truthy
except ModuleNotFoundError:
    SECRET_KEY = "forward-nautobot-plugin-test-key"
    DEBUG = False
    ALLOWED_HOSTS = ["*"]

    INSTALLED_APPS: list[str] = []
    MIDDLEWARE: list[str] = []

    USE_I18N = False
    USE_TZ = True
    LANGUAGE_CODE = "en-us"
    TIME_ZONE = "UTC"

    STATIC_URL = "/static/"
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
else:
    SECRET_KEY = SECRET_KEY or "forward-nautobot-plugin-test-key"
    DEBUG = is_truthy(os.getenv("NAUTOBOT_DEBUG", "False"))
    ALLOWED_HOSTS = os.getenv("NAUTOBOT_ALLOWED_HOSTS", "*").split()
    db_engine = os.getenv("NAUTOBOT_DB_ENGINE", "django.db.backends.sqlite3")
    if db_engine.endswith("sqlite3"):
        database_name = os.getenv("NAUTOBOT_DB_NAME", str(Path(NAUTOBOT_ROOT) / "nautobot.sqlite3"))
    else:
        database_name = os.getenv("NAUTOBOT_DB_NAME", "nautobot")
    DATABASES = {
        "default": {
            "ENGINE": db_engine,
            "NAME": database_name,
            "USER": os.getenv("NAUTOBOT_DB_USER", ""),
            "PASSWORD": os.getenv("NAUTOBOT_DB_PASSWORD", ""),
            "HOST": os.getenv("NAUTOBOT_DB_HOST", "localhost"),
            "PORT": os.getenv("NAUTOBOT_DB_PORT", ""),
            "CONN_MAX_AGE": int(os.getenv("NAUTOBOT_DB_TIMEOUT", "300")),
        }
    }
    PLUGINS = ["forward_nautobot"]
    PLUGINS_CONFIG = {}
