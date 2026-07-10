from __future__ import annotations

from forward_nautobot.integrations.forward.contrib_sync import cable_action


def _action(**over):
    base = dict(
        a_present=True,
        b_present=True,
        a_is_lag=False,
        b_is_lag=False,
        a_cable_id=None,
        b_cable_id=None,
    )
    base.update(over)
    return cable_action(**base)


def test_create_when_both_present_and_uncabled():
    assert _action() == "create"


def test_skipped_missing_when_an_endpoint_absent():
    assert _action(a_present=False) == "skipped_missing"
    assert _action(b_present=False) == "skipped_missing"


def test_skipped_lag_when_either_endpoint_is_lag():
    assert _action(a_is_lag=True) == "skipped_lag"
    assert _action(b_is_lag=True) == "skipped_lag"


def test_no_change_when_same_cable_already_connects_both():
    assert _action(a_cable_id="c1", b_cable_id="c1") == "no_change"


def test_conflict_when_one_endpoint_wired_elsewhere():
    assert _action(a_cable_id="c1") == "skipped_conflict"
    assert _action(b_cable_id="c2") == "skipped_conflict"
    # different cables on each end is still a conflict, not a no-op
    assert _action(a_cable_id="c1", b_cable_id="c2") == "skipped_conflict"
