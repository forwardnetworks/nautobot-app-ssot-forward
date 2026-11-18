"""Architecture audit: each inconsistency is found, and the shipped registry is consistent."""

from dataclasses import replace

from forward_nautobot.integrations.forward.architecture_audit import build_architecture_audit
from forward_nautobot.integrations.forward.registry import CORE_MODEL_MAPPINGS


def _codes(report):
    return {(f["code"], f["slice"]) for f in report["findings"]}


def _devices():
    return next(m for m in CORE_MODEL_MAPPINGS if m.slug == "devices")


def test_the_shipped_registry_is_fully_consistent():
    """Registry, packaged queries and contract versions must agree before release."""
    report = build_architecture_audit()
    assert report["findings"] == []
    assert report["status"] == "pass"
    assert report["slice_count"] == len(CORE_MODEL_MAPPINGS)


def test_a_slice_pointing_at_an_unpackaged_query_fails():
    bad = replace(_devices(), forward_query_file="forward_nope.nqe")
    assert ("query_not_bundled", "devices") in _codes(build_architecture_audit([bad]))


def test_a_contract_version_that_disagrees_with_the_query_header_fails():
    bad = replace(_devices(), contract_version="v999")
    report = build_architecture_audit([bad])
    assert ("contract_version_mismatch", "devices") in _codes(report)
    assert report["status"] == "fail"


def test_a_dependency_on_an_unregistered_slice_fails():
    bad = replace(_devices(), depends_on=("ghost",))
    assert ("unknown_dependency", "devices") in _codes(build_architecture_audit([bad]))


def test_a_dependency_cycle_fails():
    a = replace(_devices(), slug="a", depends_on=("b",))
    b = replace(_devices(), slug="b", depends_on=("a",))
    codes = {code for code, _ in _codes(build_architecture_audit([a, b]))}
    assert "dependency_cycle" in codes


def test_queries_no_slice_reads_are_listed_as_information_only():
    report = build_architecture_audit()
    assert "forward_cables.nqe" in report["non_slice_queries"]
    assert not any(f["slice"] == "forward_cables.nqe" for f in report["findings"])


def test_an_identity_field_missing_from_the_query_contract_fails():
    bad = replace(_devices(), identity_fields=("not_a_column",), depends_on=())
    report = build_architecture_audit([bad])
    assert ("identity_field_not_in_contract", "devices") in _codes(report)
    assert report["status"] == "fail"
