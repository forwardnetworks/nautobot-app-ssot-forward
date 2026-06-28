from __future__ import annotations

from forward_nautobot.integrations.forward.support import (
    DEFAULT_GRADE_THRESHOLDS,
    grade_support_bundle,
)


def _clean_bundle(**overrides):
    bundle = {
        "failure_classification": "clean",
        "row_count": 100,
        "diff_summary": {"create": 10, "update": 5, "no-change": 85},
        "diagnostics": {"api_usage": {"http_429": 0, "http_retries": 0}},
    }
    bundle.update(overrides)
    return bundle


def test_clean_bundle_passes():
    grade = grade_support_bundle(_clean_bundle())
    assert grade["status"] == "pass"
    assert grade["first_order_actions"] == []
    assert {c["name"] for c in grade["checks"]} == {
        "run_health",
        "delete_pressure",
        "api_throttling",
        "result_volume",
    }


def test_failed_classification_fails():
    grade = grade_support_bundle(_clean_bundle(failure_classification="row-blocked"))
    assert grade["status"] == "fail"
    assert any("row-blocked" in a for a in grade["first_order_actions"])


def test_high_delete_fraction_fails():
    grade = grade_support_bundle(
        _clean_bundle(diff_summary={"create": 0, "update": 0, "delete": 8, "no-change": 2})
    )
    assert grade["status"] == "fail"
    delete_check = next(c for c in grade["checks"] if c["name"] == "delete_pressure")
    assert delete_check["status"] == "fail"


def test_moderate_delete_fraction_warns():
    grade = grade_support_bundle(
        _clean_bundle(diff_summary={"create": 0, "update": 6, "delete": 3, "no-change": 1})
    )
    assert grade["status"] == "warn"


def test_throttling_warns():
    grade = grade_support_bundle(
        _clean_bundle(diagnostics={"api_usage": {"http_429": 3, "http_retries": 1}})
    )
    assert grade["status"] == "warn"
    assert any("throttled" in a for a in grade["first_order_actions"])


def test_empty_result_warns():
    grade = grade_support_bundle(_clean_bundle(row_count=0))
    assert grade["status"] == "warn"


def test_thresholds_are_overridable():
    # Raising the fail threshold lets an otherwise-failing delete fraction pass.
    bundle = _clean_bundle(diff_summary={"delete": 8, "no-change": 2})
    grade = grade_support_bundle(
        bundle, thresholds={"delete_fraction_warn": 0.95, "delete_fraction_fail": 0.99}
    )
    assert grade["checks"][1]["status"] == "pass"
    # Default thresholds are surfaced for transparency.
    assert set(DEFAULT_GRADE_THRESHOLDS).issubset(grade["thresholds"])
