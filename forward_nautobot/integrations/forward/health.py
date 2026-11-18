"""Pre-flight health summary: will a sync against this profile work?

Answers the operator's question before a long run starts, one check at a time,
each with a status and the action most likely to fix it. A sync that fails
twenty minutes in on a missing query or a wrong network ID wastes a run and
leaves a failure trace; these checks find the same problems in seconds.

A query that is not published is a warning, not a failure: the planner runs the
bundled source inline when no published copy exists, so the sync still works,
only without incremental diffs. A published query that differs from the bundle is
a failure, because the planner would run the old published version.

Checks run in dependency order. When connectivity fails, later checks are marked
``skipped`` rather than ``fail``: they could not be evaluated, and reporting them
as failures would bury the one real problem.

Uses only the plugin's own ``ForwardClient`` methods, so all Forward access
still goes through the SDK.
"""

from __future__ import annotations

from typing import Any

from .explain import explain_failure
from .query_publishing import audit_bundled_queries
from .registry import DEFAULT_QUERY_DIRECTORY, get_model_mapping

_RANK = {"pass": 0, "warn": 1, "fail": 2}
_PROCESSED = "processed"
#: A drop in successfully collected devices at or above this fraction, against the
#: previous snapshot, is flagged even when Forward reports no failures.
DEVICE_LOSS_WARN_FRACTION = 0.10


def _check(name: str, status: str, detail: str, action: str = "") -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail, "action": action}


def _failed(name: str, exc: Exception) -> dict[str, str]:
    explanation = explain_failure(exc)
    return _check(
        name,
        "fail",
        f"{explanation.summary} ({type(exc).__name__}: {exc})"[:300],
        explanation.next_steps[0] if explanation.next_steps else "",
    )


def run_health_check(
    client: Any,
    *,
    network_id: str,
    snapshot_id: str = "latestProcessed",
    enabled_models: tuple[str, ...] = (),
    directory: str = DEFAULT_QUERY_DIRECTORY,
    previous_snapshot_id: str = "",
) -> dict[str, Any]:
    """Run the pre-flight checks and return ``{status, checks, first_order_actions}``."""
    checks: list[dict[str, str]] = []

    # 1. Connectivity and credentials, proven by the cheapest authenticated call.
    try:
        networks = client.get_networks()
    except Exception as exc:  # noqa: BLE001 - every failure is a finding, not a crash
        checks.append(_failed("connectivity", exc))
        networks = None
    else:
        checks.append(
            _check("connectivity", "pass", f"Authenticated; {len(networks)} network(s) visible.")
        )

    if networks is None:
        for name in ("network", "snapshot", "collection", "queries"):
            checks.append(_check(name, "skipped", "Not evaluated: Forward is not reachable."))
        return _summary(checks)

    # 2. The configured network exists and is visible to this account.
    if not network_id:
        checks.append(
            _check(
                "network",
                "fail",
                "The profile has no network ID.",
                "Set the Forward network ID on the connection profile.",
            )
        )
    elif network_id not in {str(n.get("id")) for n in networks}:
        checks.append(
            _check(
                "network",
                "fail",
                "The configured network is not visible to this account.",
                "Check the network ID and the account's access to that network.",
            )
        )
    else:
        checks.append(_check("network", "pass", "The configured network is visible."))

    # 3. A snapshot can be selected and has finished processing.
    metrics: dict[str, Any] | None = None
    if checks[-1]["status"] == "fail":
        checks.append(_check("snapshot", "skipped", "Not evaluated: the network is not usable."))
        checks.append(_check("collection", "skipped", "Not evaluated: no snapshot to inspect."))
    else:
        snapshot_result, resolved, metrics = _snapshot_check(client, network_id, snapshot_id)
        checks.append(snapshot_result)
        # 3b. Did Forward collect the devices, and did any go missing since last time?
        if resolved and snapshot_result["status"] != "fail":
            checks.append(_collection_check(client, metrics, previous_snapshot_id, resolved))
        else:
            checks.append(_check("collection", "skipped", "Not evaluated: no usable snapshot."))

    # 4. The queries this profile will run are published and match the bundle.
    checks.append(_query_check(client, enabled_models, directory))
    return _summary(checks)


def _snapshot_check(
    client: Any, network_id: str, snapshot_id: str
) -> tuple[dict[str, str], str, dict[str, Any] | None]:
    """Return (check, resolved snapshot id, metrics or None)."""
    try:
        resolved = client.resolve_snapshot_id(network_id, snapshot_id)
    except Exception as exc:  # noqa: BLE001
        return _failed("snapshot", exc), "", None
    try:
        metrics = dict(client.get_snapshot_metrics(resolved))
    except Exception:  # noqa: BLE001 - metrics are unavailable until processing completes
        return (
            _check(
                "snapshot",
                "warn",
                "A snapshot was selected but its processing state could not be confirmed.",
                "Confirm the snapshot has finished processing before syncing; "
                "deletes stay disabled until it can be confirmed.",
            ),
            resolved,
            None,
        )
    state = str(metrics.get("snapshotState") or "").lower()
    if state and state != _PROCESSED:
        return (
            _check(
                "snapshot",
                "fail",
                f"The selected snapshot is '{state}', not processed.",
                "Wait for processing to finish, or select a processed snapshot.",
            ),
            resolved,
            metrics,
        )
    return _check("snapshot", "pass", "The selected snapshot is processed."), resolved, metrics


def _count(metrics: dict[str, Any] | None, key: str) -> int | None:
    """A non-negative count, or ``None`` when Forward did not report one.

    Absent is not zero: reading a missing device count as 0 would fake a drop.
    """
    value = (metrics or {}).get(key)
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _collection_check(
    client: Any, metrics: dict[str, Any] | None, previous_snapshot_id: str, resolved: str
) -> dict[str, str]:
    if metrics is None:
        return _check(
            "collection",
            "warn",
            "Collection results are unavailable, so device coverage cannot be judged.",
            "Deletes stay disabled until the snapshot's metrics can be read.",
        )
    # One definition of "complete": the planner's rule, which also gates deletes.
    from .planner import ForwardIngestionPlanner

    completeness = ForwardIngestionPlanner._snapshot_completeness(metrics)
    problems: list[str] = []
    actions: list[str] = []
    if completeness["status"] != "complete":
        problems.append(
            f"{completeness['failure_count']} device/endpoint collection or processing failure(s)"
            " reported; deletes are disabled for this snapshot"
        )
        actions.append("Fix collection in Forward, or re-run once a clean snapshot exists.")

    successful = _count(metrics, "numSuccessfulDevices")
    if successful is not None and previous_snapshot_id and previous_snapshot_id != resolved:
        try:
            previous = _count(
                client.get_snapshot_metrics(previous_snapshot_id), "numSuccessfulDevices"
            )
        except Exception:  # noqa: BLE001 - trend is advisory; absence is not a finding
            previous = None
        lost = (previous or 0) - successful
        if previous and lost > 0 and lost / previous >= DEVICE_LOSS_WARN_FRACTION:
            problems.append(
                f"{lost} fewer devices collected than the previous snapshot ({previous} to {successful})"
            )
            actions.append("Check whether devices were retired or Forward lost access to them.")
    if not problems:
        shown = "" if successful is None else f"{successful} "
        return _check("collection", "pass", f"{shown}device(s) collected with no failures.".strip())
    return _check("collection", "warn", "; ".join(problems) + ".", " ".join(actions))


def _query_check(client: Any, enabled_models: tuple[str, ...], directory: str) -> dict[str, str]:
    try:
        wanted = {get_model_mapping(slug).forward_query_file for slug in enabled_models}
    except Exception as exc:  # noqa: BLE001 - an unknown model slug is a profile error
        return _failed("queries", exc)
    try:
        report = audit_bundled_queries(client, directory=directory)
    except Exception as exc:  # noqa: BLE001
        return _failed("queries", exc)
    relevant = [q for q in report.get("queries", []) if not wanted or q["filename"] in wanted]
    stale = [q for q in relevant if q.get("status") == "stale"]
    unverified = [
        q for q in relevant if q.get("status") not in ("matched", "stale") and q.get("status")
    ]
    if stale:
        summary = ", ".join(q["filename"] for q in stale[:5])
        return _check(
            "queries",
            "fail",
            f"{len(stale)} published query(ies) differ from the bundle: {summary}.",
            "Run forward_publish_queries --profile <name> --overwrite, then re-check.",
        )
    if unverified:
        summary = ", ".join(f"{q['filename']}={q['status']}" for q in unverified[:5])
        return _check(
            "queries",
            "warn",
            f"{len(unverified)} of {len(relevant)} enabled query(ies) could not be matched: "
            f"{summary}. Unpublished queries run inline, without incremental diffs.",
            "Run forward_publish_queries --profile <name> to publish them.",
        )
    return _check("queries", "pass", f"{len(relevant)} enabled query(ies) match the bundle.")


def _summary(checks: list[dict[str, str]]) -> dict[str, Any]:
    worst = max((_RANK.get(c["status"], 0) for c in checks), default=0)
    status = {v: k for k, v in _RANK.items()}[worst]
    actions = [c["action"] for c in checks if c["status"] in ("warn", "fail") and c["action"]]
    return {"status": status, "checks": checks, "first_order_actions": actions}
