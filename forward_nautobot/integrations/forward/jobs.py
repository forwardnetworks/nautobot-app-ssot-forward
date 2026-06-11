"""Job helpers for the Forward integration."""

from collections import namedtuple
import json

from .client import ForwardClient
from ...models import ForwardConnectionProfileRecord
from .models import ForwardConnectionSettings
from .models import ForwardQuerySpec
from .models import ForwardSyncSpec
from .models import LATEST_PROCESSED_SNAPSHOT
from ...models import WRITE_DEFAULT_FIELD_NAMES
from .planner import ForwardIngestionPlanner
from .planner import ForwardIngestionRequest
from .registry import CORE_MODEL_MAPPINGS
from .write_executor import ForwardNautobotWriteExecutor
from .support import build_support_bundle_pair
from .support import classify_failure
from .runner import ForwardSyncRunner

try:
    from nautobot.apps.jobs import BooleanVar
    from nautobot.apps.jobs import ChoiceVar
    from nautobot.apps.jobs import IntegerVar
    from nautobot.apps.jobs import Job
    from nautobot.apps.jobs import StringVar
    from nautobot.apps.jobs import TextVar
    from nautobot.apps.jobs import register_jobs
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    class _Var:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class Job:  # type: ignore[too-many-ancestors]
        logger = None

    class BooleanVar(_Var):
        pass

    class ChoiceVar(_Var):
        pass

    class IntegerVar(_Var):
        pass

    class StringVar(_Var):
        pass

    class TextVar(_Var):
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

        sync = None
        job_result = None
        logger = None

        def __init__(self):
            self.dryrun = True
            self.memory_profiling = False
            self.parallel_loading = False
            self.source_adapter = None
            self.target_adapter = None

        def run(self, *args, **kwargs):
            self.dryrun = bool(kwargs.get("dryrun", True))
            self.memory_profiling = bool(kwargs.get("memory_profiling", False))
            self.parallel_loading = bool(kwargs.get("parallel_loading", False))
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


class ForwardJobBase(Job):
    base_url = StringVar(
        default="https://fwd.app",
        description="Forward API URL.",
    )
    username = StringVar(required=False, description="Forward username.")
    password = StringVar(required=False, description="Forward password.")
    network_id = StringVar(required=True, description="Forward network ID.")
    snapshot_id = StringVar(
        default=LATEST_PROCESSED_SNAPSHOT,
        required=False,
        description="Specific snapshot ID or latestProcessed.",
    )
    query_mode = ChoiceVar(
        choices=(
            ("query_path", "Repository Query Path"),
            ("query_id", "Published Query ID"),
            ("query_text", "Inline NQE"),
        ),
        default="query_path",
        description="How the Forward query is referenced.",
    )
    query_repository = StringVar(
        default="org",
        required=False,
        description="Forward repository name for query_path mode.",
    )
    query_path = StringVar(required=False, description="Repository query path.")
    query_commit_id = StringVar(
        default="head",
        required=False,
        description="Repository commit ID for query_path mode.",
    )
    query_id = StringVar(required=False, description="Direct Forward query ID.")
    query_text = TextVar(required=False, description="Inline NQE query text.")
    query_parameters_json = TextVar(
        default="{}",
        required=False,
        description="JSON object with query parameters.",
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
        description="Comma-separated model slugs to include in the preview.",
    )
    profile_name = StringVar(
        required=False,
        default="job-profile",
        description="Name for the Forward connection profile.",
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
    apply_writes = BooleanVar(
        default=False,
        required=False,
        description="Apply the planned writes to Nautobot.",
    )

    def _build_connection_settings(self, **data):
        return ForwardConnectionSettings(
            base_url=data["base_url"],
            username=data.get("username") or "",
            password=data.get("password") or "",
            network_id=data.get("network_id") or "",
            snapshot_id=data.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT,
        )

    def _build_query_spec(self, **data):
        query_mode = data.get("query_mode") or "query_path"
        parameters = {}
        raw_parameters = data.get("query_parameters_json") or "{}"
        if raw_parameters:
            try:
                parsed = json.loads(raw_parameters)
                if isinstance(parsed, dict):
                    parameters = parsed
            except json.JSONDecodeError:
                parameters = {}
        if query_mode == "query_path":
            return ForwardQuerySpec(
                query_path=data.get("query_path") or "",
                query_repository=data.get("query_repository") or "org",
                commit_id=data.get("query_commit_id") or "head",
                parameters=parameters,
            )
        if query_mode == "query_id":
            return ForwardQuerySpec(
                query_id=data.get("query_id") or "",
                parameters=parameters,
            )
        return ForwardQuerySpec(
            query_text=data.get("query_text") or "",
            parameters=parameters,
        )

    def _build_connection_profile(self, **data):
        return ForwardConnectionProfileRecord(
            name=str(data.get("profile_name") or "job-profile").strip() or "job-profile",
            base_url=data["base_url"],
            username=data.get("username") or "",
            password=data.get("password") or "",
            network_id=data.get("network_id") or "",
            snapshot_id=data.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT,
            enabled_models=_split_csv(data.get("selected_models")),
            default_location_type_name=data.get("default_location_type_name") or "",
            default_location_status_name=data.get("default_location_status_name") or "",
            default_device_role_name=data.get("default_device_role_name") or "",
            default_device_status_name=data.get("default_device_status_name") or "",
            delete_policy=data.get("delete_policy") or "ignore",
        )

    def _build_spec(self, mode, **data):
        connection = self._build_connection_settings(**data)
        query = self._build_query_spec(**data)
        selected_models = _split_csv(data.get("selected_models"))
        limit = int(data.get("limit") or 0)
        return ForwardSyncSpec(
            mode=mode,
            connection=connection,
            query=query,
            fetch_all=bool(data.get("fetch_all", True)),
            limit=limit or None,
            model_names=selected_models,
        )

    def _run(self, mode, **data):
        spec = self._build_spec(mode, **data)
        client = ForwardClient(spec.connection)
        runner = ForwardSyncRunner(client)
        report = runner.preview(spec) if mode == "preview" else runner.sync(spec)
        if getattr(self, "logger", None):
            self.logger.info(report.summary)
        return report.as_dict()


class ForwardInventoryPreview(ForwardJobBase):
    class Meta:
        name = "Forward inventory preview"
        description = "Preview the Forward -> Nautobot sync boundary."

    def run(self, **data):
        return self._run("preview", **data)


class ForwardInventorySync(ForwardJobBase):
    class Meta:
        name = "Forward inventory sync report"
        description = "Report on the Forward -> Nautobot sync boundary."

    def run(self, **data):
        return self._run("sync", **data)


class ForwardIngestionPlanJob(Job):
    base_url = StringVar(
        default="https://fwd.app",
        description="Forward API URL.",
    )
    username = StringVar(required=False, description="Forward username.")
    password = StringVar(required=False, description="Forward password.")
    network_id = StringVar(required=True, description="Forward network ID.")
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
        description="Comma-separated model slugs to include in the plan.",
    )
    profile_name = StringVar(
        required=False,
        default="plan-profile",
        description="Name for the Forward connection profile.",
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

    def _build_connection_settings(self, **data):
        return ForwardConnectionSettings(
            base_url=data["base_url"],
            username=data.get("username") or "",
            password=data.get("password") or "",
            network_id=data.get("network_id") or "",
            snapshot_id=data.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT,
        )

    def _build_connection_profile(self, **data):
        return ForwardConnectionProfileRecord(
            name=str(data.get("profile_name") or "plan-profile").strip() or "plan-profile",
            base_url=data["base_url"],
            username=data.get("username") or "",
            password=data.get("password") or "",
            network_id=data.get("network_id") or "",
            snapshot_id=data.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT,
            enabled_models=_split_csv(data.get("selected_models")),
            default_location_type_name=data.get("default_location_type_name") or "",
            default_location_status_name=data.get("default_location_status_name") or "",
            default_device_role_name=data.get("default_device_role_name") or "",
            default_device_status_name=data.get("default_device_status_name") or "",
            delete_policy=data.get("delete_policy") or "ignore",
        )

    def _build_request(self, **data):
        connection = self._build_connection_settings(**data)
        selected_models = _split_csv(data.get("selected_models"))
        limit = int(data.get("limit") or 0)
        connection_profile = self._build_connection_profile(**data)
        if not (data.get("apply_writes") or _has_meaningful_profile_inputs(data)):
            connection_profile = None
        return ForwardIngestionRequest(
            connection=connection,
            model_names=selected_models,
            fetch_all=bool(data.get("fetch_all", True)),
            limit=limit or None,
            snapshot_id=data.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT,
            connection_profile=connection_profile,
        )

    def _execute_ingestion_plan(self, **data):
        request = self._build_request(**data)
        client = ForwardClient(request.connection)
        planner = ForwardIngestionPlanner(client)
        plan = planner.run(request)
        apply_writes = bool(data.get("apply_writes"))
        write_execution = {}
        if apply_writes:
            write_execution = ForwardNautobotWriteExecutor().execute(
                plan.write_plan,
                request.connection_profile,
            ).as_dict()
        bundle = {}
        shared_bundle = {}
        profile_status = {}
        failure_classification = (
            "clean"
            if not apply_writes and not plan.configuration_status.get("profile_provided")
            else classify_failure(
                write_summary=plan.write_summary,
                configuration_status=plan.configuration_status,
            )
        )
        if apply_writes and write_execution:
            failure_classification = str(
                write_execution.get("failure_classification") or failure_classification
            )
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
                sharing_profile=str(
                    data.get("support_bundle_sharing_profile") or "external"
                ).strip()
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

    def run(self, **data):
        result, _plan, _write_execution = self._execute_ingestion_plan(**data)
        return result


class ForwardInventoryDataSource(DataSource, ForwardIngestionPlanJob):
    """SSoT DataSource wrapper for Forward inventory ingestion."""

    support_bundle_sharing_profile = ChoiceVar(
        choices=(
            ("external", "External support bundle"),
            ("internal", "Internal support bundle"),
        ),
        default="external",
        required=False,
        description="Redaction profile to use for the shared support bundle.",
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
            "Query source": "Bundled Forward NQE contracts.",
            "Write behavior": "SSoT dry run plans only; non-dry-run applies supported Nautobot writes.",
        }

    def run(self, *args, **kwargs):
        """Capture Forward-specific job inputs, then let SSoT own the run lifecycle."""
        self._forward_job_data = dict(kwargs)
        return super().run(*args, **kwargs)

    def _save_sync_result(self, plan):
        sync = getattr(self, "sync", None)
        if sync is None:
            return
        try:
            sync.diff = plan.diff_detail
            if hasattr(sync, "summary"):
                sync.summary = plan.diff_summary
            sync.save()
        except Exception as error:  # pragma: no cover - defensive for version-specific models
            if getattr(self, "logger", None):
                self.logger.warning("Unable to save Forward SSoT diff summary: %s", error)

    def sync_data(self, memory_profiling=False):
        """Run the existing Forward planner under the SSoT DataSource lifecycle."""
        del memory_profiling
        data = dict(getattr(self, "_forward_job_data", {}))
        data["apply_writes"] = not bool(getattr(self, "dryrun", True))
        result, plan, _write_execution = self._execute_ingestion_plan(**data)
        self.source_adapter = plan.source
        self.target_adapter = plan.target
        self._save_sync_result(plan)
        if getattr(self, "logger", None):
            self.logger.info("Forward SSoT sync summary: %s", result["diff_summary"])
        return result


register_jobs(
    ForwardInventoryDataSource,
    ForwardInventoryPreview,
    ForwardInventorySync,
    ForwardIngestionPlanJob,
)
