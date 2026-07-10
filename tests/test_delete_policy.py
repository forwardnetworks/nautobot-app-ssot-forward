from __future__ import annotations

from forward_nautobot.integrations.forward.delete_policy import (
    DeleteDecision,
    allowed_models,
    build_delete_audit,
    evaluate_model_deletes,
)


def test_no_deletes_is_allowed():
    d = evaluate_model_deletes("device", target_count=10, source_count=10, would_delete=0)
    assert d.allowed and d.reason == ""


def test_zero_rows_gate_blocks():
    d = evaluate_model_deletes("device", target_count=10, source_count=0, would_delete=10)
    assert not d.allowed
    assert "0 rows" in d.reason


def test_zero_rows_gate_override_allows():
    d = evaluate_model_deletes(
        "device", target_count=10, source_count=0, would_delete=10, override=True
    )
    assert d.allowed
    assert d.reason.startswith("override")


def test_fraction_gate_blocks_over_threshold():
    # 5/10 = 50% > default 25%
    d = evaluate_model_deletes(
        "device", target_count=10, source_count=5, would_delete=5, max_fraction=0.25
    )
    assert not d.allowed
    assert "exceeds" in d.reason


def test_fraction_gate_allows_under_threshold():
    # 1/10 = 10% < 25%
    d = evaluate_model_deletes(
        "device", target_count=10, source_count=9, would_delete=1, max_fraction=0.25
    )
    assert d.allowed and d.reason == ""


def test_fraction_gate_override_allows():
    d = evaluate_model_deletes(
        "device", target_count=10, source_count=5, would_delete=5, max_fraction=0.25, override=True
    )
    assert d.allowed and d.reason.startswith("override")


def test_build_audit_buckets_and_override_record():
    decisions = [
        DeleteDecision("a", 10, 9, 1, True, ""),  # allowed
        DeleteDecision("b", 10, 0, 10, False, "blocked: source returned 0 rows..."),  # blocked
        DeleteDecision("c", 10, 5, 5, True, "override: 5/10 ..."),  # overridden
        DeleteDecision("d", 5, 5, 0, True, ""),  # no deletes -> excluded
    ]
    audit = build_delete_audit(
        decisions,
        allow_delete=True,
        user="alice",
        override_reason="cutover",
        at="2026-07-09T00:00:00",
    )
    assert audit["allow_delete"] is True
    assert audit["deletes_allowed_models"] == ["a"]
    assert [b["model"] for b in audit["deletes_blocked"]] == ["b"]
    assert [o["model"] for o in audit["deletes_overridden"]] == ["c"]
    assert audit["override"] == {"user": "alice", "reason": "cutover", "at": "2026-07-09T00:00:00"}


def test_build_audit_no_override_record_when_none_overridden():
    decisions = [DeleteDecision("a", 10, 9, 1, True, "")]
    audit = build_delete_audit(decisions, allow_delete=True)
    assert "override" not in audit


def test_allowed_models_helper():
    decisions = [
        DeleteDecision("a", 1, 1, 0, True, ""),
        DeleteDecision("b", 1, 0, 1, False, "blocked"),
    ]
    assert allowed_models(decisions) == {"a"}
