from __future__ import annotations

from forward_nautobot.integrations.forward.normalize import normalize_location_key


def test_merges_street_suffix_and_case_variants():
    a = normalize_location_key("8ng5+500 W 30TH ST+NEW YORK+NY+10001")
    b = normalize_location_key("8ng5+500 W 30TH STREET+NEW YORK+NY+10001")
    assert a == b, "ST and STREET variants of one site must collapse to one key"


def test_keeps_distinct_addresses_distinct():
    a = normalize_location_key("8ng5+500 W 30TH ST+NEW YORK+NY+10001")
    c = normalize_location_key("8ng5+500 W 33rd St+NY+NY+10001")
    assert a != c, "different street number / city must stay distinct"


def test_collapses_whitespace_and_punctuation():
    assert normalize_location_key("500   W  30th   St") == normalize_location_key("500 W 30th St")
    assert normalize_location_key("500 W 30th St") == "500 w 30th street"


def test_expands_common_suffixes():
    assert normalize_location_key("1 Main Ave") == normalize_location_key("1 Main Avenue")
    assert normalize_location_key("2 Oak Rd") == normalize_location_key("2 Oak Road")
    assert normalize_location_key("3 Sun Blvd") == normalize_location_key("3 Sun Boulevard")


def test_blank_input_returns_empty():
    assert normalize_location_key("") == ""
    assert normalize_location_key("   ") == ""
    assert normalize_location_key(None) == ""
