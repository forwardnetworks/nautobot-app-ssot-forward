"""Job scaffolding for the Forward integration."""

import json

from .client import ForwardClient
from .models import ForwardConnectionSettings
from .models import ForwardQuerySpec
from .models import ForwardSyncSpec
from .models import LATEST_PROCESSED_SNAPSHOT
from .planner import ForwardIngestionPlanner
from .planner import ForwardIngestionRequest
from .support import build_support_bundle
from .runner import ForwardSyncRunner

try:
    from nautobot.apps.jobs import BooleanVar
    from nautobot.apps.jobs import ChoiceVar
    from nautobot.apps.jobs import IntegerVar
    from nautobot.apps.jobs import Job
    from nautobot.apps.jobs import StringVar
    from nautobot.apps.jobs import TextVar
    from nautobot.apps.jobs import register_jobs
except ModuleNotFoundError:  # pragma: no cover - local scaffold import path
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


def _split_csv(value):
    if not value:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(part.strip() for part in str(value).split(",") if part.strip())


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
        name = "Forward inventory sync"
        description = "Sync Forward data into Nautobot."

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

    def _build_connection_settings(self, **data):
        return ForwardConnectionSettings(
            base_url=data["base_url"],
            username=data.get("username") or "",
            password=data.get("password") or "",
            network_id=data.get("network_id") or "",
            snapshot_id=data.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT,
        )

    def _build_request(self, **data):
        connection = self._build_connection_settings(**data)
        selected_models = _split_csv(data.get("selected_models"))
        limit = int(data.get("limit") or 0)
        return ForwardIngestionRequest(
            connection=connection,
            model_names=selected_models,
            fetch_all=bool(data.get("fetch_all", True)),
            limit=limit or None,
            snapshot_id=data.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT,
        )

    def run(self, **data):
        request = self._build_request(**data)
        client = ForwardClient(request.connection)
        planner = ForwardIngestionPlanner(client)
        plan = planner.run(request)
        bundle = {}
        if plan.reports:
            bundle = build_support_bundle(
                plan.reports[0],
                source_summary=plan.source_summary,
                target_summary=plan.target_summary,
                diagnostics={
                    "diff_summary": plan.diff_summary,
                    "diff_detail": plan.diff_detail,
                },
            ).as_dict()
        return {
            "reports": [report.as_dict() for report in plan.reports],
            "source_summary": plan.source_summary,
            "target_summary": plan.target_summary,
            "diff_summary": plan.diff_summary,
            "support_bundle": bundle,
        }


register_jobs(ForwardInventoryPreview, ForwardInventorySync, ForwardIngestionPlanJob)
