"""Packaged sample fixture and profile helpers for the Forward plugin."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from .integrations.forward.registry import CORE_MODEL_MAPPINGS
from .integrations.forward.registry import CORE_MODEL_SLUGS
from .models import ForwardConnectionProfile
from .models import ForwardConnectionProfileRecord

PROFILE_NAME = "replay"
FIXTURE_NAME = "forward_sample_ingestion.json"


def profile_record() -> ForwardConnectionProfileRecord:
    """Return the canonical seeded profile."""

    return ForwardConnectionProfileRecord(
        name=PROFILE_NAME,
        base_url="https://fwd.app",
        username="replay-user",
        password="replay-password",
        network_id="replay-network",
        snapshot_id="latestProcessed",
        enabled_models=CORE_MODEL_SLUGS,
        query_contract_version="v1",
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
        delete_policy="mark_inactive",
        is_default=True,
    )


def fixture_resource():
    return files("forward_nautobot.fixtures").joinpath(FIXTURE_NAME)


def fixture_path() -> str:
    return str(fixture_resource())


def fixture_payload() -> dict[str, list[dict[str, Any]]]:
    return json.loads(fixture_resource().read_text(encoding="utf-8"))


def fixture_coverage() -> tuple[dict[str, Any], ...]:
    """Summarize the packaged fixture by model slice."""

    payload = fixture_payload()
    coverage: list[dict[str, Any]] = []
    for mapping in CORE_MODEL_MAPPINGS:
        rows = tuple(payload.get(mapping.slug, []) or ())
        sample_rows = tuple(dict(row) for row in rows[:2] if isinstance(row, dict))
        sample_key = ""
        if sample_rows:
            first_row = sample_rows[0]
            sample_key = "|".join(
                str(first_row.get(field_name) or "").strip()
                for field_name in mapping.identity_fields
                if str(first_row.get(field_name) or "").strip()
            )
        coverage.append(
            {
                "slug": mapping.slug,
                "description": mapping.description,
                "contract_version": mapping.contract_version,
                "count": len(rows),
                "sample_key": sample_key,
                "sample_rows": sample_rows,
            }
        )
    return tuple(coverage)


def seed_profile(manager=None) -> ForwardConnectionProfileRecord | None:
    """Create or update the seeded profile."""

    profile = profile_record()
    manager = manager or getattr(ForwardConnectionProfile, "objects", None)
    if manager is None:
        return profile

    existing = None
    if hasattr(manager, "get"):
        try:
            existing = manager.get(name=profile.name)
        except Exception:  # pragma: no cover - defensive
            existing = None

    data = profile.as_dict()
    data["enabled_models"] = list(profile.enabled_models)
    defaults = {key: value for key, value in data.items() if key != "name"}

    if hasattr(manager, "update_or_create"):
        obj, _created = manager.update_or_create(name=profile.name, defaults=defaults)
    elif existing is not None:
        obj = existing
        for key, value in defaults.items():
            setattr(obj, key, value)
        if hasattr(obj, "save"):
            obj.save()
    elif hasattr(manager, "create"):
        obj = manager.create(name=profile.name, **defaults)
    else:  # pragma: no cover - defensive
        return None

    if profile.is_default and hasattr(manager, "all"):
        try:
            for other in manager.all():
                if getattr(other, "name", None) == profile.name:
                    continue
                if getattr(other, "is_default", False):
                    setattr(other, "is_default", False)
                    if hasattr(other, "save"):
                        other.save(update_fields=["is_default"])
        except Exception:  # pragma: no cover - defensive
            pass

    return obj.to_record() if hasattr(obj, "to_record") else profile
