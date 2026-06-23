from __future__ import annotations

from forward_nautobot.integrations.forward.contrib_sync import LocationCanonicalizer


def test_canonicalizer_collapses_variants_to_first_seen():
    c = LocationCanonicalizer()
    c.add("8ng5+500 W 30TH ST+NEW YORK+NY+10001")
    c.add("8ng5+500 W 30TH STREET+NEW YORK+NY+10001")  # variant of the same site
    # One canonical name for the site; the first-seen raw wins.
    assert c.names == ["8ng5+500 W 30TH ST+NEW YORK+NY+10001"]
    # A device referencing the STREET variant maps to the same canonical Location.
    assert (
        c.canonical("8ng5+500 W 30TH STREET+NEW YORK+NY+10001")
        == "8ng5+500 W 30TH ST+NEW YORK+NY+10001"
    )


def test_canonicalizer_keeps_distinct_addresses_separate():
    c = LocationCanonicalizer()
    c.add("8ng5+500 W 30TH ST+NEW YORK+NY+10001")
    c.add("8ng5+500 W 33rd St+NY+NY+10001")  # genuinely different address
    assert len(c.names) == 2


def test_canonicalizer_unknown_raw_passes_through():
    c = LocationCanonicalizer()
    c.add("known site")
    # An unseen location string is returned as-is (stripped), not dropped.
    assert c.canonical("  somewhere else  ") == "somewhere else"


def test_canonicalizer_ignores_blank():
    c = LocationCanonicalizer()
    c.add("")
    c.add("   ")
    assert c.names == []
