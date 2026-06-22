"""Job helpers for the Forward integration."""

from __future__ import annotations

import re
from collections import namedtuple
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

from ...models import (
    WRITE_DEFAULT_FIELD_NAMES,
    ForwardConnectionProfile,
    ForwardConnectionProfileRecord,
)
from .client import ForwardClient
from .models import LATEST_PROCESSED_SNAPSHOT, ForwardConnectionSettings
from .planner import ForwardIngestionPlanner, ForwardIngestionRequest
from .registry import CORE_MODEL_MAPPINGS, get_model_mapping
from .support import build_support_bundle_pair, classify_failure
from .write_executor import ForwardNautobotWriteExecutor

try:
    from django.apps import apps as django_apps
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    django_apps = None

try:
    from nautobot.apps.jobs import BooleanVar, ChoiceVar, IntegerVar, StringVar, register_jobs
except Exception:  # pragma: no cover - local compatibility import path

    class _Var:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class BooleanVar(_Var):
        pass

    class ChoiceVar(_Var):
        pass

    class IntegerVar(_Var):
        pass

    class StringVar(_Var):
        pass

    def register_jobs(*jobs):  # type: ignore[no-redef]
        return None


try:
    from nautobot_ssot.jobs.base import DataMapping, DataSource
except Exception:  # pragma: no cover - local compatibility import path
    DataMapping = namedtuple(
        "DataMapping",
        ["source_name", "source_url", "target_name", "target_url"],
    )

    class DataSource:  # type: ignore[too-many-ancestors]
        """Fallback SSoT base for local tests without nautobot-ssot installed."""

        logger = None
        job_result = None

        def __init__(self):
            self.dryrun = True
            self.memory_profiling = False
            self.parallel_loading = False
            self.sync = None
            self.source_adapter = None
            self.target_adapter = None

        def run(self, *args, **kwargs):
            self.dryrun = bool(kwargs.get("dryrun", True))
            self.memory_profiling = bool(kwargs.get("memory_profiling", False))
            self.parallel_loading = bool(kwargs.get("parallel_loading", False))
            self.sync = SimpleNamespace(
                source=getattr(self.__class__, "data_source", "Forward Networks"),
                target=getattr(self.__class__, "data_target", "Nautobot"),
                dry_run=self.dryrun,
                job_result=self.job_result,
                start_time=datetime.now(),
                diff={},
                summary={},
                save=lambda *args, **kwargs: None,
            )
            return self.sync_data(self.memory_profiling)


def _split_csv(value):
    if not value:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(part.strip() for part in str(value).split(",") if part.strip())


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on", "y"}


def _has_meaningful_profile_inputs(data) -> bool:
    profile_name = str(data.get("profile_name") or "").strip()
    if profile_name and profile_name not in {"job-profile", "plan-profile"}:
        return True
    for field_name in WRITE_DEFAULT_FIELD_NAMES:
        if str(data.get(field_name) or "").strip():
            return True
    delete_policy = str(data.get("delete_policy") or "ignore").strip()
    return delete_policy != "ignore"


def _split_unique_id(unique_id: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(unique_id or "").split("|") if part.strip())


def _normalized_lookup_key(model_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(model_name or "").split(".", 1)[-1].lower())


LOOKUP_ALIASES: dict[str, tuple[str, str] | str] = {
    "devicetype": "_lookup_device_type",
    "locationtype": ("dcim", "LocationType"),
    "role": ("extras", "Role"),
    "status": ("extras", "Status"),
    "manufacturer": ("dcim", "Manufacturer"),
    "platform": ("dcim", "Platform"),
    "moduletype": "_lookup_module_type",
}


def _iter_persisted_profile_records() -> tuple[ForwardConnectionProfileRecord, ...]:
    manager = getattr(ForwardConnectionProfile, "objects", None)
    if manager is None or not hasattr(manager, "all"):
        return ()
    try:
        records = manager.all()
    except Exception:  # pragma: no cover - defensive
        return ()
    return tuple(
        record.to_record() if hasattr(record, "to_record") else record for record in records
    )


def _resolve_profile_record(**data):
    profile_name = str(data.get("profile_name") or "").strip()
    profiles = _iter_persisted_profile_records()
    selected = None
    if profile_name:
        for profile in profiles:
            if profile.name == profile_name:
                selected = profile
                break
    elif profiles:
        for profile in profiles:
            if profile.is_default:
                selected = profile
                break
        if selected is None:
            selected = profiles[0]

    if selected is not None:
        return ForwardConnectionProfileRecord.from_mapping(
            data,
            default_name=selected.name,
            existing=selected,
        )
    if profile_name or _has_meaningful_profile_inputs(data):
        return ForwardConnectionProfileRecord.from_mapping(
            data,
            default_name=profile_name or "job-profile",
        )
    return None


def _save_profile_record(
    record: ForwardConnectionProfileRecord,
    *,
    manager=None,
) -> ForwardConnectionProfileRecord | None:
    manager = manager or getattr(ForwardConnectionProfile, "objects", None)
    if manager is None:
        return None
    existing = None
    if hasattr(manager, "get"):
        try:
            existing = manager.get(name=record.name)
        except Exception:  # pragma: no cover - defensive
            existing = None
    if existing is not None and not record.password:
        record = replace(record, password=str(getattr(existing, "password", "") or ""))
    data = record.as_dict()
    data["enabled_models"] = list(record.enabled_models)
    defaults = {key: value for key, value in data.items() if key != "name"}
    if hasattr(manager, "update_or_create"):
        obj, _created = manager.update_or_create(name=record.name, defaults=defaults)
    elif existing is not None:
        obj = existing
        for key, value in defaults.items():
            setattr(obj, key, value)
        if hasattr(obj, "save"):
            obj.save()
    elif hasattr(manager, "create"):
        obj = manager.create(name=record.name, **defaults)
    else:  # pragma: no cover - defensive
        return None

    if record.is_default and hasattr(manager, "all"):
        try:
            for other in manager.all():
                if getattr(other, "name", None) == record.name:
                    continue
                if getattr(other, "is_default", False):
                    other.is_default = False
                    if hasattr(other, "save"):
                        other.save(update_fields=["is_default"])
        except Exception:  # pragma: no cover - defensive
            pass

    return obj.to_record() if hasattr(obj, "to_record") else record


def _build_connection_settings(**data):
    return ForwardConnectionSettings(
        base_url=data["base_url"],
        username=data.get("username") or "",
        password=data.get("password") or "",
        network_id=data.get("network_id") or "",
        snapshot_id=data.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT,
        verify_tls=_coerce_bool(data["verify_tls"]) if "verify_tls" in data else True,
    )


def _build_ingestion_request(*, dryrun: bool, **data):
    connection_profile = _resolve_profile_record(**data)
    selected_models = _split_csv(data.get("selected_models"))
    if not selected_models and connection_profile is not None:
        selected_models = tuple(connection_profile.enabled_models)
    limit = int(data.get("limit") or 0)
    if connection_profile is None and dryrun and not _has_meaningful_profile_inputs(data):
        connection_profile = None
    if connection_profile is not None:
        connection = connection_profile.to_connection_settings()
    else:
        connection = _build_connection_settings(**data)
    return ForwardIngestionRequest(
        connection=connection,
        model_names=selected_models,
        fetch_all=bool(data.get("fetch_all", True)),
        limit=limit or None,
        snapshot_id=data.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT,
        connection_profile=connection_profile,
    )


def _run_ingestion_plan(*, dryrun: bool, **data):
    request = _build_ingestion_request(dryrun=dryrun, **data)
    client = ForwardClient(request.connection)
    planner = ForwardIngestionPlanner(client)
    try:
        plan = planner.run(request)
    except Exception as exc:
        # A hard failure (auth/TLS/network/NQE) must leave a failure trace on the
        # profile so the operator does not see a stale "last success". Record it
        # without advancing last_snapshot_id, then re-raise so SSoT marks the job
        # failed.
        if not dryrun and request.connection_profile is not None:
            failed = request.connection_profile.with_run_history(
                last_run_at=datetime.now().isoformat(timespec="seconds"),
                last_failure=f"error: {type(exc).__name__}: {exc}"[:500],
            )
            _save_profile_record(failed)
        raise
    write_execution = {}
    if not dryrun:
        write_execution = (
            ForwardNautobotWriteExecutor()
            .execute(
                plan.write_plan,
                request.connection_profile,
            )
            .as_dict()
        )

    failure_classification = (
        "clean"
        if dryrun and not plan.configuration_status.get("profile_provided")
        else classify_failure(
            write_summary=plan.write_summary,
            configuration_status=plan.configuration_status,
        )
    )
    if not dryrun and write_execution:
        failure_classification = str(
            write_execution.get("failure_classification") or failure_classification
        )

    bundle = {}
    shared_bundle = {}
    profile_status = {}
    if plan.diff_detail.get("skipped") and request.connection_profile is not None:
        # Snapshot unchanged — no NQE ran, no report to build.
        # Still stamp last_run_at so the UI reflects when we last checked.
        run_at = datetime.now().isoformat(timespec="seconds")
        prof = request.connection_profile.with_run_history(
            last_run_at=run_at,
            last_failure="",
        )
        if not dryrun:
            saved_profile = _save_profile_record(prof)
            if saved_profile is not None:
                prof = saved_profile
        profile_status = prof.status_record(last_run=run_at).as_dict()
    elif plan.reports:
        bundle, shared_bundle = build_support_bundle_pair(
            plan.reports[0],
            source_summary=plan.source_summary,
            target_summary=plan.target_summary,
            write_summary=plan.write_summary,
            diff_summary=plan.diff_summary,
            write_policy=plan.write_plan.slice_policies,
            configuration_status=plan.configuration_status,
            failure_classification=failure_classification,
            diagnostics={
                "write_summary": plan.write_summary,
                "configuration_status": plan.configuration_status,
                "diff_summary": plan.diff_summary,
                "write_policy": plan.write_plan.slice_policies,
                "diff_detail": plan.diff_detail,
                "write_execution_summary": write_execution.get("summary", {}),
            },
            sharing_profile=str(data.get("support_bundle_sharing_profile") or "external").strip()
            or "external",
        )
        bundle = bundle.as_dict()
        if request.connection_profile is not None:
            is_clean = failure_classification == "clean"
            prof = request.connection_profile.with_run_history(
                last_run_at=str(bundle.get("generated_at") or ""),
                last_failure="" if is_clean else str(failure_classification or ""),
                last_support_bundle=str(bundle.get("query_reference") or ""),
                last_query_reference=str(bundle.get("query_reference") or ""),
                last_query_mode=str(plan.reports[0].query_mode or ""),
                # Only advance the snapshot baseline on a clean run. Advancing it on
                # a failed/blocked run would let skip-if-same-snapshot skip
                # re-syncing a snapshot whose write never succeeded.
                last_snapshot_id=str(plan.reports[0].snapshot_id or "") if is_clean else "",
            )
            # Persist run history on EVERY non-dryrun run (clean or not) so the
            # Status/Diagnostics UI reflects failures instead of the last success.
            if not dryrun:
                saved_profile = _save_profile_record(prof)
                if saved_profile is not None:
                    prof = saved_profile
            profile_status = prof.status_record(
                last_run=str(bundle.get("generated_at") or "not recorded")
            ).as_dict()

    result = {
        "reports": [report.as_dict() for report in plan.reports],
        "source_summary": plan.source_summary,
        "target_summary": plan.target_summary,
        "write_summary": plan.write_summary,
        "configuration_status": plan.configuration_status,
        "failure_classification": failure_classification,
        "write_execution": write_execution,
        "diff_summary": plan.diff_summary,
        "support_bundle": bundle,
        "support_bundle_shared": shared_bundle,
        "profile_status": profile_status,
    }
    return result, plan, write_execution


class ForwardInventoryDataSource(DataSource):  # pylint: disable=too-many-instance-attributes
    """SSoT DataSource wrapper for Forward inventory ingestion."""

    class_path = f"{__name__}.ForwardInventoryDataSource"
    name = "Forward Networks inventory"
    grouping = "Forward Networks"
    description = "Sync Forward Networks inventory data into Nautobot through the SSoT app."
    read_only = False
    console_log_default = False
    dryrun_default = True
    hidden = False
    has_sensitive_variables = True
    supports_dryrun = True
    is_singleton = False
    soft_time_limit = 0
    time_limit = 0
    task_queues: tuple[str, ...] = ()

    base_url = StringVar(default="https://fwd.app", description="Forward API URL.")
    username = StringVar(required=False, description="Forward username.")
    password = StringVar(required=False, description="Forward password.")
    network_id = StringVar(required=False, description="Forward network ID.")
    snapshot_id = StringVar(
        default=LATEST_PROCESSED_SNAPSHOT,
        required=False,
        description="Specific snapshot ID or latestProcessed.",
    )
    fetch_all = BooleanVar(
        default=True,
        required=False,
        description="Fetch all NQE result pages.",
    )
    limit = IntegerVar(
        default=0,
        required=False,
        description="Page size override; 0 means use the client default.",
    )
    selected_models = StringVar(
        required=False,
        default="",
        description="Comma-separated model slugs to include in the sync, or leave blank to use the selected profile.",
    )
    profile_name = StringVar(
        required=False,
        default="",
        description="Name of the persisted Forward profile to use.",
    )
    verify_tls = BooleanVar(
        default=True,
        required=False,
        description="Validate Forward API TLS certificate.",
    )
    default_location_type_name = StringVar(
        required=False,
        default="",
        description="Default Nautobot location type used for write readiness.",
    )
    default_location_status_name = StringVar(
        required=False,
        default="",
        description="Default Nautobot location status used for write readiness.",
    )
    default_device_role_name = StringVar(
        required=False,
        default="",
        description="Default Nautobot device role used for write readiness.",
    )
    default_device_status_name = StringVar(
        required=False,
        default="",
        description="Default Nautobot device status used for write readiness.",
    )
    support_bundle_sharing_profile = ChoiceVar(
        choices=(
            ("external", "External support bundle"),
            ("internal", "Internal support bundle"),
        ),
        default="external",
        required=False,
        description="Redaction profile to use for the shared support bundle.",
    )
    delete_policy = ChoiceVar(
        choices=(
            ("ignore", "Ignore missing rows"),
            ("mark_inactive", "Mark missing rows inactive"),
            ("delete", "Delete missing rows"),
        ),
        default="ignore",
        required=False,
        description="How missing source rows should be handled.",
    )

    class Meta:
        name = "Forward Networks inventory"
        description = "Sync Forward Networks inventory data into Nautobot through the SSoT app."
        data_source = "Forward Networks"
        dryrun_default = True

    @classmethod
    def data_mappings(cls):
        """Describe the Forward query slices surfaced to the SSoT dashboard."""
        return [
            DataMapping(
                source_name=f"Forward {mapping.slug}",
                source_url="",
                target_name=mapping.nautobot_scope,
                target_url="",
            )
            for mapping in CORE_MODEL_MAPPINGS
        ]

    @classmethod
    def config_information(cls):
        """Describe user-visible configuration without exposing sensitive values."""
        return {
            "Setup flow": "Use the Forward configuration page to save a profile, then select it from the SSoT job form.",
            "Forward API URL": "Optional job-time override when you do not want to use the saved profile value.",
            "Forward network": "Optional job-time override when you do not want to use the saved profile value.",
            "Forward TLS verification": "Optional override (on by default) for certificate validation against custom Forward hosts.",
            "Snapshot": f"Defaults to {LATEST_PROCESSED_SNAPSHOT}.",
            "Profile selection": "Uses a persisted profile by name or the default saved profile when available.",
            "Model selection": "Use selected_models to override a saved profile's enabled model set; leave it blank to use the profile defaults.",
            "Query input": "Bundled Forward NQE contracts only.",
            "Write behavior": "SSoT dry run plans only; non-dry-run applies supported Nautobot writes.",
        }

    @staticmethod
    def _lookup_model_object(app_label: str, model_name: str, **lookup):
        if django_apps is None:
            return None
        candidates = tuple(
            dict.fromkeys(
                candidate
                for candidate in (
                    str(model_name or "").strip(),
                    str(model_name or "").strip().lower(),
                    str(model_name or "").strip().capitalize(),
                )
                if candidate
            )
        )
        for candidate in candidates:
            try:
                model = django_apps.get_model(app_label, candidate)
            except Exception:
                continue
            if model is None:
                continue
            manager = getattr(model, "objects", None)
            if manager is None or not hasattr(manager, "get"):
                continue
            try:
                return manager.get(**lookup)
            except Exception:
                continue
        return None

    def _lookup_by_name(self, app_label: str, model_name: str, unique_id: str):
        return self._lookup_model_object(app_label, model_name, name=unique_id)

    def _lookup_device_type(self, unique_id: str):
        found = self._lookup_model_object("dcim", "DeviceType", model=unique_id)
        if found is None:
            found = self._lookup_model_object("dcim", "DeviceType", name=unique_id)
        return found

    def _lookup_module_type(self, unique_id: str):
        found = self._lookup_model_object("dcim", "ModuleType", model=unique_id)
        if found is None:
            found = self._lookup_model_object("dcim", "ModuleType", name=unique_id)
        return found

    def _lookup_device_interface(self, unique_id: str):
        parts = _split_unique_id(unique_id)
        if len(parts) != 2:
            return None
        device = self.lookup_object("devices", parts[0])
        if device is None:
            return None
        return self._lookup_model_object("dcim", "Interface", device=device, name=parts[1])

    def _lookup_location_vid(self, unique_id: str):
        parts = _split_unique_id(unique_id)
        if len(parts) != 2:
            return None
        location = self.lookup_object("locations", parts[0])
        lookup = {"vid": int(parts[1])}
        if location is not None:
            lookup["location"] = location
        return self._lookup_model_object("ipam", "VLAN", **lookup)

    def _lookup_prefix_vrf(self, unique_id: str):
        parts = _split_unique_id(unique_id)
        if not parts:
            return None
        lookup = {"prefix": parts[0]}
        if len(parts) > 1 and parts[1] not in {"", "default"}:
            vrf = self.lookup_object("vrfs", parts[1])
            if vrf is not None:
                lookup["vrf"] = vrf
        return self._lookup_model_object("ipam", "Prefix", **lookup)

    def _lookup_device_interface_address_vrf(self, unique_id: str):
        parts = _split_unique_id(unique_id)
        if len(parts) != 4:
            return None
        device = self.lookup_object("devices", parts[0])
        if device is None:
            return None
        interface = self._lookup_model_object("dcim", "Interface", device=device, name=parts[1])
        if interface is None:
            return None
        lookup = {"address": parts[2]}
        if parts[3] not in {"", "default"}:
            vrf = self.lookup_object("vrfs", parts[3])
            if vrf is not None:
                lookup["vrf"] = vrf
        return self._lookup_model_object("ipam", "IPAddress", **lookup)

    def _lookup_device_name(self, unique_id: str):
        parts = _split_unique_id(unique_id)
        if len(parts) != 2:
            return None
        device = self.lookup_object("devices", parts[0])
        if device is None:
            return None
        return self._lookup_model_object("dcim", "InventoryItem", device=device, name=parts[1])

    def _lookup_device_module_bay(self, unique_id: str):
        parts = _split_unique_id(unique_id)
        if len(parts) != 2:
            return None
        device = self.lookup_object("devices", parts[0])
        if device is None:
            return None
        return self._lookup_model_object(
            "dcim", "Module", device=device, module_bay__position=parts[1]
        )

    @staticmethod
    def _mapping_for_lookup(model_name: str):
        model_slug = str(model_name or "").strip()
        if not model_slug:
            return None
        try:
            return get_model_mapping(model_slug)
        except Exception:
            pass
        for mapping in CORE_MODEL_MAPPINGS:
            if model_slug == mapping.nautobot_scope:
                return mapping
            scope_tail = mapping.nautobot_scope.split(".", 1)[-1]
            if model_slug == scope_tail:
                return mapping
        return None

    def lookup_object(self, model_name, unique_id):
        """Resolve a Nautobot object for SSoT log attribution when possible."""
        model_slug = str(model_name or "").strip()
        unique_id = str(unique_id or "").strip()
        if not model_slug or not unique_id:
            return None
        alias = LOOKUP_ALIASES.get(_normalized_lookup_key(model_slug))
        if alias is not None:
            if isinstance(alias, tuple):
                return self._lookup_by_name(alias[0], alias[1], unique_id)
            return getattr(self, alias)(unique_id)
        mapping = self._mapping_for_lookup(model_slug)
        if mapping is None:
            return None
        if mapping.lookup_strategy == "name":
            scope = mapping.nautobot_scope.split(".", 1)
            if len(scope) != 2:
                return None
            return self._lookup_by_name(scope[0], scope[1], unique_id)
        strategy = getattr(self, f"_lookup_{mapping.lookup_strategy}", None)
        if strategy is None:
            return None
        return strategy(unique_id)

    def run(self, *args, **kwargs):
        """Capture Forward-specific job inputs, then let SSoT own the run lifecycle."""
        self._forward_job_data = dict(kwargs)
        return super().run(*args, **kwargs)

    def sync_data(self, memory_profiling=False):
        """Run the existing Forward planner under the SSoT DataSource lifecycle."""
        del memory_profiling
        data = dict(getattr(self, "_forward_job_data", {}))
        data.pop("dryrun", None)
        result, plan, _write_execution = _run_ingestion_plan(
            dryrun=bool(getattr(self, "dryrun", True)),
            **data,
        )
        self.source_adapter = plan.source
        self.target_adapter = plan.target
        if getattr(self, "sync", None) is not None:
            self.sync.diff = plan.diff_detail
            if hasattr(self.sync, "summary"):
                self.sync.summary = plan.diff_summary
            self.sync.save()
        if getattr(self, "logger", None):
            self.logger.info("Forward SSoT sync summary: %s", result["diff_summary"])
        return result


jobs = [ForwardInventoryDataSource]

if all(hasattr(job, "class_path") for job in jobs):
    register_jobs(*jobs)
