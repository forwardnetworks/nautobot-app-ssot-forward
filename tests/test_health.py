"""Pre-flight health: each check reports pass/warn/fail with an action; failures cascade as skips."""

import pytest

from forward_nautobot.integrations.forward import health
from forward_nautobot.integrations.forward.exceptions import ForwardClientError
from forward_nautobot.integrations.forward.registry import get_model_mapping

DEVICES_FILE = get_model_mapping("devices").forward_query_file


class _Client:
    def __init__(
        self,
        *,
        networks=None,
        snapshot="snap-1",
        state="PROCESSED",
        error=None,
        extra=None,
        previous=None,
    ):
        self._networks = [{"id": "net-1", "name": "Primary"}] if networks is None else networks
        self._snapshot = snapshot
        self._state = state
        self._error = error
        self._extra = extra or {}
        self._previous = previous  # metrics for "snap-0", or None when unavailable

    def get_networks(self):
        if self._error:
            raise self._error
        return self._networks

    def resolve_snapshot_id(self, network_id, snapshot_id):
        return self._snapshot

    def get_snapshot_metrics(self, snapshot_id):
        if snapshot_id == "snap-0":
            if self._previous is None:
                raise ForwardClientError("no metrics for the previous snapshot")
            return self._previous
        if self._state is None:
            raise ForwardClientError("metrics unavailable")
        return {"snapshotState": self._state, "numSuccessfulDevices": 100, **self._extra}


def _audit(devices="matched", other="stale"):
    return lambda client, directory: {
        "queries": [
            {"filename": DEVICES_FILE, "path": "/x", "status": devices},
            {"filename": "some_other_slice.nqe", "path": "/y", "status": other},
        ]
    }


def _run(client, monkeypatch, audit=None, models=("devices",), network="net-1", previous=""):
    monkeypatch.setattr(health, "audit_bundled_queries", audit or _audit())
    return health.run_health_check(
        client,
        network_id=network,
        snapshot_id="latestProcessed",
        enabled_models=models,
        previous_snapshot_id=previous,
    )


def _by_name(report):
    return {c["name"]: c for c in report["checks"]}


def test_healthy_profile_passes_every_check(monkeypatch):
    report = _run(_Client(), monkeypatch)
    assert report["status"] == "pass"
    assert [c["name"] for c in report["checks"]] == [
        "connectivity",
        "network",
        "snapshot",
        "collection",
        "queries",
    ]
    assert [c["status"] for c in report["checks"]] == ["pass"] * 5
    assert report["first_order_actions"] == []


def test_unreachable_forward_fails_once_and_skips_the_rest(monkeypatch):
    err = ForwardClientError("401")
    err.kind = "ForwardAuthError"
    report = _run(_Client(error=err), monkeypatch)
    checks = _by_name(report)
    assert report["status"] == "fail"
    assert checks["connectivity"]["status"] == "fail"
    assert "credentials" in checks["connectivity"]["detail"]
    assert checks["connectivity"]["action"]
    assert {checks[n]["status"] for n in ("network", "snapshot", "collection", "queries")} == {
        "skipped"
    }


def test_network_not_visible_to_the_account_fails_with_an_action(monkeypatch):
    report = _run(_Client(networks=[{"id": "other", "name": "O"}]), monkeypatch)
    checks = _by_name(report)
    assert checks["network"]["status"] == "fail"
    assert checks["network"]["action"]
    assert checks["snapshot"]["status"] == "skipped"


def test_missing_network_id_fails(monkeypatch):
    assert _by_name(_run(_Client(), monkeypatch, network=""))["network"]["status"] == "fail"


def test_snapshot_still_processing_fails(monkeypatch):
    report = _run(_Client(state="PROCESSING"), monkeypatch)
    assert _by_name(report)["snapshot"]["status"] == "fail"


def test_unconfirmable_snapshot_state_warns_rather_than_fails(monkeypatch):
    # Forward answers 404 for the metrics of an unprocessed snapshot; the SDK raises.
    report = _run(_Client(state=None), monkeypatch)
    assert _by_name(report)["snapshot"]["status"] == "warn"
    assert report["status"] == "warn"


def test_collection_failures_warn_and_say_deletes_are_disabled(monkeypatch):
    report = _run(_Client(extra={"numCollectionFailureDevices": 3}), monkeypatch)
    collection = _by_name(report)["collection"]
    assert collection["status"] == "warn"
    assert "deletes are disabled" in collection["detail"]
    assert collection["action"]
    assert report["status"] == "warn"


def test_devices_vanishing_since_the_previous_snapshot_warn_without_any_reported_failure(
    monkeypatch,
):
    client = _Client(previous={"numSuccessfulDevices": 150})  # 150 -> 100 is a third lost
    collection = _by_name(_run(client, monkeypatch, previous="snap-0"))["collection"]
    assert collection["status"] == "warn"
    assert "50 fewer devices" in collection["detail"]


def test_a_small_drop_in_devices_is_not_flagged(monkeypatch):
    client = _Client(previous={"numSuccessfulDevices": 105})  # 5% is under the threshold
    assert _by_name(_run(client, monkeypatch, previous="snap-0"))["collection"]["status"] == "pass"


def test_missing_previous_metrics_never_become_a_finding(monkeypatch):
    client = _Client(previous=None)
    assert _by_name(_run(client, monkeypatch, previous="snap-0"))["collection"]["status"] == "pass"


def test_comparing_a_snapshot_with_itself_is_skipped(monkeypatch):
    client = _Client(snapshot="snap-1", previous={"numSuccessfulDevices": 999})
    assert _by_name(_run(client, monkeypatch, previous="snap-1"))["collection"]["status"] == "pass"


def test_a_stale_query_for_an_enabled_model_fails(monkeypatch):
    # A published query that differs from the bundle is what the planner would run.
    report = _run(_Client(), monkeypatch, audit=_audit(devices="stale"))
    queries = _by_name(report)["queries"]
    assert queries["status"] == "fail"
    assert DEVICES_FILE in queries["detail"]
    assert "forward_publish_queries" in queries["action"]


def test_an_unpublished_query_warns_because_the_sync_still_runs_inline(monkeypatch):
    report = _run(_Client(), monkeypatch, audit=_audit(devices="missing"))
    queries = _by_name(report)["queries"]
    assert queries["status"] == "warn"
    assert "without incremental diffs" in queries["detail"]
    assert report["status"] == "warn"


def test_a_missing_device_count_is_unknown_not_zero(monkeypatch):
    """Absent must not read as 0 devices, which would fake a drop from the previous snapshot."""

    class _NoCount(_Client):
        def get_snapshot_metrics(self, snapshot_id):
            if snapshot_id == "snap-0":
                return {"numSuccessfulDevices": 150}
            return {"snapshotState": "PROCESSED"}

    collection = _by_name(_run(_NoCount(), monkeypatch, previous="snap-0"))["collection"]
    assert collection["status"] == "pass"


def test_a_stale_query_for_a_model_that_is_not_enabled_is_ignored(monkeypatch):
    report = _run(_Client(), monkeypatch, audit=_audit(devices="matched", other="missing"))
    assert _by_name(report)["queries"]["status"] == "pass"


def test_an_unknown_enabled_model_is_reported_not_raised(monkeypatch):
    report = _run(_Client(), monkeypatch, models=("not-a-model",))
    assert _by_name(report)["queries"]["status"] == "fail"


@pytest.mark.parametrize("status", ["pass", "warn", "fail"])
def test_overall_status_is_the_worst_check(status):
    checks = [
        {"name": "a", "status": "pass", "detail": "", "action": ""},
        {"name": "b", "status": status, "detail": "", "action": "do x"},
    ]
    assert health._summary(checks)["status"] == status
