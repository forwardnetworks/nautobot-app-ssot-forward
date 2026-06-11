"""Job helpers for the Forward integration."""

from __future__ import annotations

from collections import namedtuple
from datetime import datetime
from types import SimpleNamespace

from .client import ForwardClient
from ...models import ForwardConnectionProfile
from ...models import ForwardConnectionProfileRecord
from .models import ForwardConnectionSettings
from .models import LATEST_PROCESSED_SNAPSHOT
from ...models import WRITE_DEFAULT_FIELD_NAMES
from .planner import ForwardIngestionPlanner
from .planner import ForwardIngestionRequest
from .registry import CORE_MODEL_MAPPINGS
from .support import build_support_bundle_pair
from .support import classify_failure
from .write_executor import ForwardNautobotWriteExecutor

try:
    from django.apps import apps as django_apps
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    django_apps = None

try:
    from nautobot.apps.jobs import BooleanVar
    from nautobot.apps.jobs import ChoiceVar
    from nautobot.apps.jobs import IntegerVar
    from nautobot.apps.jobs import StringVar
    from nautobot.apps.jobs import register_jobs
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
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
    from nautobot_ssot.jobs.base import DataMapping
    from nautobot_ssot.jobs.base import DataSource
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
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


def _iter_persisted_profile_records() -> tuple[ForwardConnectionProfileRecord, ...]:
    manager = getattr(ForwardConnectionProfile, "objects", None)
    if manager is None or not hasattr(manager, "all"):
        return ()
    try:
        records = manager.all()
    except Exception:  # pragma: no cover - defensive
        return ()
    return tuple(
        record.to_record() if hasattr(record, "to_record") else record
        for record in records
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


def _build_connection_settings(**data):
    return ForwardConnectionSettings(
        base_url=data["base_url"],
        username=data.get("username") or "",
        password=data.get("password") or "",
        network_id=data.get("network_id") or "",
        snapshot_id=data.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT,
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
    plan = planner.run(request)
    write_execution = {}
    if not dryrun:
        write_execution = ForwardNautobotWriteExecutor().execute(
            plan.write_plan,
            request.connection_profile,
        ).as_dict()

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
    if plan.reports:
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
            prof = request.connection_profile.with_run_history(
                last_run_at=str(bundle.get("generated_at") or ""),
                last_failure=str(failure_classification or ""),
                last_support_bundle=str(bundle.get("query_reference") or ""),
            )
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
            "Forward API URL": "Provided at job runtime.",
            "Forward network": "Provided at job runtime.",
            "Snapshot": f"Defaults to {LATEST_PROCESSED_SNAPSHOT}.",
            "Profile selection": "Uses a persisted profile by name or the default saved profile when available.",
            "Query input": "Bundled Forward NQE contracts only.",
            "Write behavior": "SSoT dry run plans only; non-dry-run applies supported Nautobot writes.",
        }

    @staticmethod
    def _lookup_model_object(app_label: str, model_name: str, **lookup):
        if django_apps is None:
            return None
        try:
            model = django_apps.get_model(app_label, model_name)
        except Exception:
            return None
        if model is None:
            return None
        manager = getattr(model, "objects", None)
        if manager is None or not hasattr(manager, "get"):
            return None
        try:
            return manager.get(**lookup)
        except Exception:
            return None

    def lookup_object(self, model_name, unique_id):
        """Resolve a Nautobot object for SSoT log attribution when possible."""
        model_slug = str(model_name or "").strip()
        unique_id = str(unique_id or "").strip()
        if not model_slug or not unique_id:
            return None
        if model_slug == "locations":
            return self._lookup_model_object("dcim", "Location", name=unique_id)
        if model_slug == "platforms":
            return self._lookup_model_object("dcim", "Platform", name=unique_id)
        if model_slug == "device_types":
            found = self._lookup_model_object("dcim", "DeviceType", model=unique_id)
            if found is None:
                found = self._lookup_model_object("dcim", "DeviceType", name=unique_id)
            return found
        if model_slug == "devices":
            return self._lookup_model_object("dcim", "Device", name=unique_id)
        if model_slug == "interfaces":
            parts = _split_unique_id(unique_id)
            if len(parts) != 2:
                return None
            device = self.lookup_object("devices", parts[0])
            if device is None:
                return None
            return self._lookup_model_object("dcim", "Interface", device=device, name=parts[1])
        if model_slug == "vlans":
            parts = _split_unique_id(unique_id)
            if len(parts) != 2:
                return None
            location = self.lookup_object("locations", parts[0])
            lookup = {"vid": int(parts[1])}
            if location is not None:
                lookup["location"] = location
            return self._lookup_model_object("ipam", "VLAN", **lookup)
        if model_slug == "vrfs":
            return self._lookup_model_object("ipam", "VRF", name=unique_id)
        if model_slug in {"ipv4_prefixes", "ipv6_prefixes"}:
            parts = _split_unique_id(unique_id)
            if not parts:
                return None
            lookup = {"prefix": parts[0]}
            if len(parts) > 1 and parts[1]:
                vrf = self.lookup_object("vrfs", parts[1])
                if vrf is not None:
                    lookup["vrf"] = vrf
            return self._lookup_model_object("ipam", "Prefix", **lookup)
        if model_slug == "ip_addresses":
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
            if parts[3]:
                vrf = self.lookup_object("vrfs", parts[3])
                if vrf is not None:
                    lookup["vrf"] = vrf
            return self._lookup_model_object("ipam", "IPAddress", **lookup)
        if model_slug == "inventory_items":
            parts = _split_unique_id(unique_id)
            if len(parts) != 2:
                return None
            device = self.lookup_object("devices", parts[0])
            if device is None:
                return None
            return self._lookup_model_object("dcim", "InventoryItem", device=device, name=parts[1])
        if model_slug == "modules":
            parts = _split_unique_id(unique_id)
            if len(parts) != 2:
                return None
            device = self.lookup_object("devices", parts[0])
            if device is None:
                return None
            return self._lookup_model_object("dcim", "Module", device=device, module_bay__position=parts[1])
        return None

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

register_jobs(*jobs)
