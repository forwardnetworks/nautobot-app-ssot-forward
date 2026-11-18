"""Drift explanations: counts, field names and next steps, never values or override text."""

from forward_nautobot.integrations.forward.drift import explain_drift


def _detail(models, changed=None):
    return {"models": models, "changed_fields": changed or {}}


def test_in_sync_slices_are_not_listed():
    out = explain_drift(_detail({"devices": {"create": 0, "update": 0, "no-change": 40}}))
    assert out["drift_slices"] == []


def test_creates_and_updates_are_counted_and_the_driving_fields_named():
    out = explain_drift(
        _detail(
            {"devices": {"create": 2, "update": 5, "no-change": 93}},
            {"devices": {"serial": 4, "role": 1}},
        )
    )
    (devices,) = out["drift_slices"]
    assert (devices["drift_slice"], devices["create"], devices["update"]) == ("devices", 2, 5)
    assert "2 object(s) exist in Forward but not in Nautobot" in devices["drift_explanation"]
    assert "serial (4)" in devices["drift_explanation"]
    assert devices["drift_action"] == ""


def test_a_mostly_changed_slice_is_flagged_as_a_probable_rename():
    out = explain_drift(_detail({"vlans": {"create": 0, "update": 80, "no-change": 20}}))
    (vlans,) = out["drift_slices"]
    assert "naming or normalization" in vlans["drift_explanation"]
    assert vlans["drift_action"]


def test_a_filtered_run_says_deletes_are_never_driven_by_the_filter():
    notes = explain_drift(_detail({}), {"filtered_scope": True})["notes"]
    assert any("Filtered run" in n for n in notes)


def test_incomplete_snapshot_explains_why_deletes_are_off():
    status = {
        "destructive_reconciliation_enabled": False,
        "snapshot_completeness": {"reason": "snapshot metrics report collection failures"},
    }
    notes = explain_drift(_detail({}), status)["notes"]
    assert any("Deletes are disabled" in n and "collection failures" in n for n in notes)


def test_ignore_policy_is_explained():
    notes = explain_drift(_detail({}), {"delete_policy": "ignore"})["notes"]
    assert any("'ignore'" in n for n in notes)


def test_blocked_and_overridden_deletes_are_reported_without_the_operators_reason():
    governance = {
        "network": {
            "deletes_blocked": [{"model": "dcim.device", "would_delete": 9, "reason": "too many"}],
            "deletes_overridden": [
                {"model": "dcim.vlan", "would_delete": 2, "reason": "override: SECRET-TICKET-77"}
            ],
            "override": {"user": "alice", "reason": "SECRET-TICKET-77", "at": "now"},
        }
    }
    notes = explain_drift(_detail({}), {"delete_policy": "delete"}, governance)["notes"]
    joined = " ".join(notes)
    assert "9 delete(s) of dcim.device were blocked" in joined
    assert "2 delete(s) of dcim.vlan went ahead under an operator override" in joined
    assert "SECRET-TICKET-77" not in joined
    assert "alice" not in joined


def test_missing_or_malformed_input_never_raises():
    assert explain_drift(None) == {"drift_slices": [], "notes": []}
    out = explain_drift({"models": {"x": {"create": "n/a"}}}, None, {"d": "not-a-dict"})
    assert out["drift_slices"] == []


def test_external_sharing_keeps_the_explanations_and_still_hides_other_diagnostics():
    from forward_nautobot.integrations.forward.support import redact_support_bundle_payload

    explanation = explain_drift(_detail({"devices": {"create": 3, "update": 0, "no-change": 1}}))
    bundle = {"diagnostics": {"drift_explanations": explanation, "internal_note": "10.0.0.1"}}

    shared = redact_support_bundle_payload(bundle, sharing_profile="external")

    kept = shared["diagnostics"]["drift_explanations"]["drift_slices"][0]
    assert "3 object(s) exist in Forward" in kept["drift_explanation"]
    assert shared["diagnostics"]["internal_note"] == "[REDACTED]"


def test_drift_keys_do_not_widen_what_other_bundle_sections_reveal():
    """The drift keys are specific, so generic names elsewhere stay redacted externally."""
    from forward_nautobot.integrations.forward.support import redact_support_bundle_payload

    bundle = {
        "diagnostics": {
            "drift_explanations": explain_drift(
                _detail({"devices": {"create": 1, "update": 0, "no-change": 0}})
            ),
            "other": {"slice": "secret-slice", "action": "secret-action", "explanation": "secret"},
        }
    }
    shared = redact_support_bundle_payload(bundle, sharing_profile="external")
    assert shared["diagnostics"]["other"] == {
        "slice": "[REDACTED]",
        "action": "[REDACTED]",
        "explanation": "[REDACTED]",
    }
