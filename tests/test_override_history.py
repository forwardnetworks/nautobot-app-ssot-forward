"""Applied delete overrides are kept as their own durable rows."""

import pytest

from forward_nautobot.integrations.forward.override_history import (
    overrides_from_execution,
    record_delete_overrides,
)


def _execution(*, overridden=True, blocked=False):
    audit = {
        "allow_delete": True,
        "deletes_allowed_models": [],
        "deletes_blocked": [{"model": "dcim.vlan", "would_delete": 5}] if blocked else [],
        "deletes_overridden": (
            [{"model": "dcim.device", "would_delete": 9, "target_count": 20, "reason": "override"}]
            if overridden
            else []
        ),
    }
    if overridden:
        audit["override"] = {"user": "alice", "reason": "TICKET-1", "at": "now"}
    return {"engine": "contrib", "summaries": {"network": {"delete_governance": audit}}}


def test_an_applied_override_yields_one_record_with_who_why_and_what():
    record = overrides_from_execution(_execution())
    assert record["user"] == "alice"
    assert record["reason"] == "TICKET-1"
    assert record["overridden"] == [
        {"domain": "network", "model": "dcim.device", "would_delete": 9, "target_count": 20}
    ]


def test_a_blocked_delete_is_not_an_override_and_leaves_no_record():
    assert overrides_from_execution(_execution(overridden=False, blocked=True)) is None


@pytest.mark.parametrize("execution", [None, {}, {"summaries": {}}, {"summaries": {"x": "no"}}])
def test_runs_without_governance_data_leave_no_record(execution):
    assert overrides_from_execution(execution) is None


class _Objects:
    def __init__(self, on_create=None, existing=None):
        self.created = []
        self._on_create = on_create
        self._existing = existing

    def create(self, **kwargs):
        if self._on_create:
            raise self._on_create
        self.created.append(kwargs)

    def filter(self, **kwargs):
        outer = self

        class _Q:
            def first(self):
                return outer._existing

        return _Q()


def _stub_models(monkeypatch, *, overrides, profile=None):
    import importlib

    # Resolve through sys.modules, which is what the code under test imports from.
    # The package attribute can lag behind it after another test swaps the module.
    plugin_models = importlib.import_module("forward_nautobot.models")

    monkeypatch.setattr(
        plugin_models, "ForwardDeleteOverride", type("O", (), {"objects": overrides})
    )
    monkeypatch.setattr(
        plugin_models,
        "ForwardConnectionProfile",
        type("P", (), {"objects": _Objects(existing=profile)}),
    )


def test_recording_maps_the_run_onto_one_row_linked_to_the_profile(monkeypatch):
    overrides = _Objects()
    profile = object()
    _stub_models(monkeypatch, overrides=overrides, profile=profile)

    wrote = record_delete_overrides(
        profile_name="p1", snapshot_id="snap-9", write_execution=_execution()
    )

    assert wrote is True
    (row,) = overrides.created
    assert row["profile"] is profile
    assert (row["profile_name"], row["snapshot_id"]) == ("p1", "snap-9")
    assert (row["user"], row["reason"]) == ("alice", "TICKET-1")
    assert row["overridden"][0]["model"] == "dcim.device"


def test_a_run_without_an_override_writes_nothing(monkeypatch):
    overrides = _Objects()
    _stub_models(monkeypatch, overrides=overrides)
    assert not record_delete_overrides(
        profile_name="p", snapshot_id="s", write_execution=_execution(overridden=False)
    )
    assert overrides.created == []


def test_a_storage_failure_is_swallowed_because_the_deletes_already_happened(monkeypatch, caplog):
    _stub_models(monkeypatch, overrides=_Objects(on_create=RuntimeError("database went away")))
    with caplog.at_level("ERROR"):
        result = record_delete_overrides(
            profile_name="p", snapshot_id="s", write_execution=_execution()
        )
    assert result is False
    assert "Could not record the applied delete override" in caplog.text


def _jobs_module():
    pytest.importorskip("nautobot")
    import importlib

    # The submodule directly: the package attribute is a lazy export, not the module.
    return importlib.import_module("forward_nautobot.integrations.forward.jobs")


def _plan(snapshot="snap-3"):
    from types import SimpleNamespace

    return SimpleNamespace(diff_detail={"current_snapshot_id": snapshot})


def test_the_job_hook_records_under_the_profile_name_and_snapshot(monkeypatch):
    jobs = _jobs_module()
    overrides = _Objects()
    _stub_models(monkeypatch, overrides=overrides)
    profile = type("Prof", (), {"name": "p-hook"})()

    jobs._record_applied_overrides(profile, _plan(), _execution())

    (row,) = overrides.created
    assert (row["profile_name"], row["snapshot_id"]) == ("p-hook", "snap-3")


def test_the_job_hook_does_nothing_without_a_profile(monkeypatch):
    jobs = _jobs_module()
    overrides = _Objects()
    _stub_models(monkeypatch, overrides=overrides)
    jobs._record_applied_overrides(None, _plan(), _execution())
    assert overrides.created == []


def test_an_override_applied_before_a_later_domain_failed_is_still_recorded(monkeypatch):
    """Core can delete under an override, then ipam_assets raises: the audit row must exist."""
    jobs = _jobs_module()
    overrides = _Objects()
    _stub_models(monkeypatch, overrides=overrides)
    partial = _execution()["summaries"]

    failure = RuntimeError("ipam_assets failed")
    failure.partial_summaries = partial
    profile = type("Prof", (), {"name": "p-partial"})()

    # What the job does when run_contrib_full_sync raises.
    recorded = getattr(failure, "partial_summaries", None) or {}
    jobs._record_applied_overrides(profile, _plan(), {"summaries": recorded})

    assert [r["profile_name"] for r in overrides.created] == ["p-partial"]
