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
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    CONSTANCE_BACKEND = "constance.backends.memory.MemoryBackend"
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
    # A running Nautobot server needs a Redis-backed cache (it calls
    # cache.delete_pattern, which LocMemCache lacks) and the database-backed
    # Constance. When NAUTOBOT_REDIS_HOST is set (the container stack) keep
    # Nautobot's imported Redis defaults; otherwise fall back to in-process
    # backends so a plain `pytest` run needs neither Redis nor a database.
    if not os.getenv("NAUTOBOT_REDIS_HOST"):
        CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
        CONSTANCE_BACKEND = "constance.backends.memory.MemoryBackend"
    PLUGINS = ["forward_nautobot"]
    PLUGINS_CONFIG = {}
