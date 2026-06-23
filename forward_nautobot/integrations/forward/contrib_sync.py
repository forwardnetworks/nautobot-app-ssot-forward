"""Phase-1 proof-of-concept: write Forward data through nautobot-ssot contrib.

This is the de-risking spike for the DiffSync/NautobotModel CRUD redesign
(docs/03_Plans/active/2026-06-23-diffsync-crud-redesign.md). It implements the
*locations* slice end to end through the standard contrib path:

    source rows -> ForwardContribLocation(NautobotModel) -> source.sync_to(target)

so create/update/delete and FK resolution come from the framework, not the
hand-rolled write_executor. Locations dedup is done in the SOURCE adapter
(collapse formatting variants to one canonical row) because contrib keys on the
diffsync identifiers and would otherwise re-create one Nautobot Location per
variant.

The module imports safely when nautobot-ssot/Django are unavailable (unit/CI
env): CONTRIB_AVAILABLE is False and the model/adapter classes are not defined.
It is exercised by the live WF smoke on a real Nautobot, not by the DB-less
unit suite.
"""

from __future__ import annotations

from typing import Any

from .normalize import normalize_location_key

try:
    from diffsync import Adapter
    from django.contrib.contenttypes.models import ContentType
    from nautobot.dcim.models import Location, LocationType
    from nautobot.extras.models import Status
    from nautobot_ssot.contrib import NautobotAdapter, NautobotModel

    CONTRIB_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only in a real Nautobot env
    CONTRIB_AVAILABLE = False


if CONTRIB_AVAILABLE:

    class ForwardContribLocation(NautobotModel):
        """Location synced through contrib CRUD. FKs resolved by lookup."""

        _model = Location
        _modelname = "location"
        _identifiers = ("name",)
        _attributes = ("location_type__name", "status__name")

        name: str
        location_type__name: str
        status__name: str

    class ForwardContribLocationTarget(NautobotAdapter):
        """Loads current Nautobot Locations via the ORM."""

        top_level = ["location"]
        location = ForwardContribLocation

    class ForwardContribLocationSource(Adapter):
        """Builds Location diffsync objects from raw Forward rows, deduped."""

        top_level = ["location"]
        location = ForwardContribLocation

        def __init__(
            self,
            rows: list[dict[str, Any]],
            *,
            location_type_name: str,
            status_name: str,
            **kwargs,
        ):
            super().__init__(**kwargs)
            self._rows = rows
            self._location_type_name = location_type_name
            self._status_name = status_name

        def load(self):
            # Dedup formatting variants of the same physical site to one canonical
            # row (first-seen name wins), so contrib creates one Location per site.
            seen: set[str] = set()
            for row in self._rows:
                raw_name = str(row.get("name") or "").strip()
                key = normalize_location_key(raw_name)
                if not key or key in seen:
                    continue
                seen.add(key)
                self.add(
                    ForwardContribLocation(
                        name=raw_name,
                        location_type__name=self._location_type_name,
                        status__name=self._status_name,
                    )
                )

    class _StubJob:
        """Minimal job object satisfying NautobotAdapter (logger + no metadata)."""

        class _Logger:
            def _noop(self, *args, **kwargs):
                return None

            info = warning = error = debug = _noop

        logger = _Logger()


def ensure_location_prerequisites(location_type_name: str, status_name: str):
    """Create the LocationType/Status the locations slice needs, with the Location
    content-type attached to the Status. Contrib resolves these by lookup and will
    raise if they are absent, so they must exist before sync."""
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")
    LocationType.objects.get_or_create(name=location_type_name)
    status, _ = Status.objects.get_or_create(name=status_name)
    ct = ContentType.objects.get_for_model(Location)
    if not status.content_types.filter(pk=ct.pk).exists():
        status.content_types.add(ct)


def run_contrib_location_sync(
    rows: list[dict[str, Any]],
    *,
    location_type_name: str,
    status_name: str,
    dryrun: bool,
    job: Any | None = None,
) -> dict[str, int]:
    """Sync Forward location rows into Nautobot via the contrib CRUD path.

    Returns the diffsync summary. On dryrun, computes the diff without applying.
    """
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")
    ensure_location_prerequisites(location_type_name, status_name)
    job = job or _StubJob()
    target = ForwardContribLocationTarget(job=job)
    target.load()
    source = ForwardContribLocationSource(
        rows, location_type_name=location_type_name, status_name=status_name
    )
    source.load()
    diff = source.diff_to(target)
    summary = dict(diff.summary())
    if not dryrun:
        source.sync_to(target)
    return summary
