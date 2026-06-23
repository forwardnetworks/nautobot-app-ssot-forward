from __future__ import annotations

from types import SimpleNamespace

from forward_nautobot.integrations.forward.contrib_sync import (
    LocationCanonicalizer,
    _profile_defaults,
    cloud_provider_name,
    cloud_resource_type_name,
)


def test_profile_defaults_reads_profile_with_fallbacks():
    prof = SimpleNamespace(
        default_location_type_name="Building",
        default_location_status_name="",
        default_device_role_name="Core",
        default_device_status_name=None,
    )
    d = _profile_defaults(prof)
    assert d["location_type_name"] == "Building"
    assert d["location_status_name"] == "Active"  # blank -> fallback
    assert d["device_role_name"] == "Core"
    assert d["device_status_name"] == "Active"  # None -> fallback


def test_profile_defaults_all_fallbacks_for_empty_profile():
    d = _profile_defaults(SimpleNamespace())
    assert d == {
        "location_type_name": "Site",
        "location_status_name": "Active",
        "device_role_name": "Network Device",
        "device_status_name": "Active",
    }


def test_cloud_provider_name_maps_known_and_falls_back():
    assert cloud_provider_name("AWS") == "Amazon Web Services"
    assert cloud_provider_name("azure") == "Microsoft Azure"
    assert cloud_provider_name("GCP") == "Google Cloud Platform"
    assert cloud_provider_name("weird") == "WEIRD"
    assert cloud_provider_name("") == "Cloud"


def test_cloud_provider_name_strips_enum_prefix():
    # Forward's toString yields "CloudType.AWS" etc.
    assert cloud_provider_name("CloudType.AWS") == "Amazon Web Services"
    assert cloud_provider_name("CloudType.GCP") == "Google Cloud Platform"
    assert cloud_provider_name("CloudType.AZURE") == "Microsoft Azure"


def test_cloud_resource_type_name_pretty():
    assert cloud_resource_type_name("AWS", "vpc") == "AWS VPC"
    assert cloud_resource_type_name("aws", "subnet") == "AWS Subnet"
    assert cloud_resource_type_name("AZURE", "load-balancer") == "AZURE Load Balancer"
    assert cloud_resource_type_name("GCP", "nat-gateway") == "GCP NAT Gateway"
    assert cloud_resource_type_name("CloudType.AWS", "vpc") == "AWS VPC"


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
