"""Forward integration boundary for Nautobot."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import-time hinting only
    from .client import ForwardClient
    from .models import ForwardConnectionSettings
    from .models import ForwardQuerySpec
    from .models import ForwardSnapshotInfo
    from .models import ForwardSyncReport
    from .models import ForwardSyncSpec
    from .models import LATEST_PROCESSED_SNAPSHOT
    from .registry import CORE_MODEL_MAPPINGS
    from .registry import CORE_MODEL_SLUGS
    from .registry import ForwardModelMapping
    from .registry import get_default_model_mappings
    from .registry import get_model_mappings
    from .runner import ForwardSyncRunner
    from .support import ForwardSupportBundle
    from .support import build_support_bundle


_EXPORT_MAP = {
    "ForwardClient": (".client", "ForwardClient"),
    "ForwardConnectionSettings": (".models", "ForwardConnectionSettings"),
    "ForwardQuerySpec": (".models", "ForwardQuerySpec"),
    "ForwardSnapshotInfo": (".models", "ForwardSnapshotInfo"),
    "ForwardSyncReport": (".models", "ForwardSyncReport"),
    "ForwardSyncSpec": (".models", "ForwardSyncSpec"),
    "LATEST_PROCESSED_SNAPSHOT": (".models", "LATEST_PROCESSED_SNAPSHOT"),
    "CORE_MODEL_MAPPINGS": (".registry", "CORE_MODEL_MAPPINGS"),
    "CORE_MODEL_SLUGS": (".registry", "CORE_MODEL_SLUGS"),
    "ForwardModelMapping": (".registry", "ForwardModelMapping"),
    "get_default_model_mappings": (".registry", "get_default_model_mappings"),
    "get_model_mappings": (".registry", "get_model_mappings"),
    "ForwardSyncRunner": (".runner", "ForwardSyncRunner"),
    "ForwardSupportBundle": (".support", "ForwardSupportBundle"),
    "build_support_bundle": (".support", "build_support_bundle"),
    "jobs": (".jobs", "jobs"),
}


def __getattr__(name: str):
    module_name, attr_name = _EXPORT_MAP[name]
    module = __import__(f"{__name__}{module_name}", fromlist=[attr_name])
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORT_MAP))

__all__ = [
    "CORE_MODEL_MAPPINGS",
    "CORE_MODEL_SLUGS",
    "ForwardClient",
    "ForwardConnectionSettings",
    "ForwardModelMapping",
    "ForwardQuerySpec",
    "ForwardSnapshotInfo",
    "ForwardSupportBundle",
    "ForwardSyncReport",
    "ForwardSyncRunner",
    "ForwardSyncSpec",
    "LATEST_PROCESSED_SNAPSHOT",
    "build_support_bundle",
    "get_default_model_mappings",
    "get_model_mappings",
]
