from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import forward_nautobot.integrations.forward.contrib_sync as contrib_sync
from forward_nautobot.integrations.forward.contrib_sync import (
    CONTRIB_AVAILABLE,
    LocationCanonicalizer,
    _cloud_summary_with_delete_safety,
    _normalize_mac,
    _profile_defaults,
    cloud_provider_name,
    cloud_resource_type_name,
)
from forward_nautobot.integrations.forward.exceptions import ForwardClientError


def test_normalize_mac_converges_eui_and_colon_forms():
    # The ORM returns a hyphenated EUI; Forward sends a colon string. Both must
    # canonicalize to the same value or every sync re-updates the interface.
    assert _normalize_mac("00-11-22-33-44-55") == "00:11:22:33:44:55"
    assert _normalize_mac("00:11:22:33:44:55") == "00:11:22:33:44:55"
    assert _normalize_mac("AA:BB:CC:DD:EE:FF") == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_absent_is_none():
    assert _normalize_mac(None) is None
    assert _normalize_mac("") is None
    assert _normalize_mac("   ") is None


def test_interface_slice_carries_mac_address():
    """The MAC learning is an attribute on the existing Interface slice (Nautobot 3.1
    has no standalone MACAddress model), so it must be in _attributes."""
    if not CONTRIB_AVAILABLE:
        if importlib.util.find_spec("django") is not None:
            code = """
import django
django.setup()
from forward_nautobot.integrations.forward.contrib_sync import ForwardContribInterface
assert "mac_address" in ForwardContribInterface._attributes
assert "mac_address" in ForwardContribInterface.__annotations__
"""
            env = os.environ.copy()
            env.setdefault("DJANGO_SETTINGS_MODULE", "nautobot_config")
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                capture_output=True,
            )
            assert result.returncode == 0, result.stderr
            return

        source = Path(contrib_sync.__file__).read_text()
        assert "class ForwardContribInterface" in source
        assert '"mac_address"' in source
        assert "mac_address: str | None" in source
        return

    iface = contrib_sync.ForwardContribInterface
    assert "mac_address" in iface._attributes
    assert "mac_address" in iface.__annotations__


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


def test_cloud_source_uses_stable_identity_and_preserves_display_name():
    if not CONTRIB_AVAILABLE:
        return
    source = contrib_sync.ForwardContribCloudSource(
        account_rows=[
            {"account_id": "account-1", "name": "Shared", "cloud_type": "TYPE_A"},
            {"account_id": "account-2", "name": "Shared", "cloud_type": "TYPE_A"},
        ],
        network_rows=[
            {
                "account_id": "account-1",
                "cloud_type": "TYPE_A",
                "network_id": "network-1",
                "name": "Shared network",
                "parent_id": "",
                "kind": "vpc",
                "cidrs": [],
            },
            {
                "account_id": "account-2",
                "cloud_type": "TYPE_A",
                "network_id": "network-1",
                "name": "Shared network",
                "parent_id": "",
                "kind": "vpc",
                "cidrs": [],
            },
        ],
        service_rows=[],
    )

    source.load()

    accounts = list(source.get_all("cloud_account"))
    networks = list(source.get_all("cloud_vpc"))
    assert len(accounts) == 2
    assert len({account.name for account in accounts}) == 2
    assert {account.description for account in accounts} == {"Shared"}
    assert len(networks) == 2
    assert len({network.name for network in networks}) == 2
    assert {network.description for network in networks} == {"Shared network"}
    assert {network.extra_config["forward"]["account_id"] for network in networks} == {
        "account-1",
        "account-2",
    }

    renamed = contrib_sync.ForwardContribCloudSource(
        account_rows=[
            {"account_id": "account-1", "name": "Renamed account", "cloud_type": "TYPE_A"}
        ],
        network_rows=[
            {
                "account_id": "account-1",
                "cloud_type": "TYPE_A",
                "network_id": "network-1",
                "name": "Renamed network",
                "parent_id": "",
                "kind": "vpc",
                "cidrs": [],
            }
        ],
        service_rows=[],
    )
    renamed.load()
    assert renamed.get_all("cloud_account")[0].name == accounts[0].name
    assert renamed.get_all("cloud_vpc")[0].name == networks[0].name
    assert renamed.get_all("cloud_vpc")[0].description == "Renamed network"


def test_cloud_delete_summary_reports_suppression_when_removal_is_disabled():
    suppressed = _cloud_summary_with_delete_safety({"create": 2, "delete": 7}, allow_delete=False)
    allowed = _cloud_summary_with_delete_safety({"delete": 7}, allow_delete=True)

    assert suppressed == {"create": 2, "delete": 0, "delete_suppressed": 7}
    assert allowed == {"delete": 7}


def test_cloud_source_qualifies_same_account_and_resource_ids_by_cloud_type():
    if not CONTRIB_AVAILABLE:
        return
    source = contrib_sync.ForwardContribCloudSource(
        account_rows=[
            {"account_id": "shared", "name": "One", "cloud_type": "TYPE_A"},
            {"account_id": "shared", "name": "Two", "cloud_type": "TYPE_B"},
        ],
        network_rows=[
            {
                "account_id": "shared",
                "cloud_type": cloud_type,
                "network_id": "shared-network",
                "name": "Network",
                "parent_id": "",
                "kind": "vpc",
                "cidrs": [],
            }
            for cloud_type in ("TYPE_A", "TYPE_B")
        ],
        service_rows=[],
    )

    source.load()

    assert len(source.get_all("cloud_account")) == 2
    assert len({row.name for row in source.get_all("cloud_account")}) == 2
    assert len(source.get_all("cloud_vpc")) == 2
    assert len({row.name for row in source.get_all("cloud_vpc")}) == 2


def test_cloud_source_preserves_operator_extra_config():
    if not CONTRIB_AVAILABLE:
        return
    network_name = contrib_sync.cloud_object_name(
        "network",
        "network-1",
        account_id=contrib_sync.cloud_account_identity("TYPE_A", "account-1"),
    )
    source = contrib_sync.ForwardContribCloudSource(
        account_rows=[{"account_id": "account-1", "name": "Account", "cloud_type": "TYPE_A"}],
        network_rows=[
            {
                "account_id": "account-1",
                "cloud_type": "TYPE_A",
                "network_id": "network-1",
                "name": "Network",
                "parent_id": "",
                "kind": "vpc",
                "cidrs": [],
            }
        ],
        service_rows=[],
        existing_extra_config={
            network_name: {
                "operator": {"owner": "cloud-team"},
                "forward": {"operator_note": "keep"},
            }
        },
    )

    source.load()

    config = source.get_all("cloud_vpc")[0].extra_config
    assert config["operator"] == {"owner": "cloud-team"}
    assert config["forward"]["operator_note"] == "keep"
    assert config["forward"]["network_id"] == "network-1"


def test_cloud_target_accepts_null_extra_config_from_existing_objects():
    if not CONTRIB_AVAILABLE:
        return

    for model in (
        contrib_sync.ForwardContribCloudVPC,
        contrib_sync.ForwardContribCloudSubnet,
        contrib_sync.ForwardContribCloudService,
    ):
        assert model.model_fields["extra_config"].is_required()
        assert type(None) in get_args(model.model_fields["extra_config"].annotation)


def test_cloud_target_querysets_are_limited_to_plugin_identity_names():
    if not CONTRIB_AVAILABLE:
        return

    expected_markers = {
        contrib_sync.ForwardContribCloudAccount: "account",
        contrib_sync.ForwardContribCloudVPC: "network",
        contrib_sync.ForwardContribCloudSubnet: "network",
        contrib_sync.ForwardContribCloudService: "service",
    }
    for model, marker in expected_markers.items():
        query = str(model.get_queryset().query)
        assert f"[{marker}:" in query
        assert "[0-9a-f]{16}" in query


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


def test_filtered_empty_device_scope_does_not_widen_cable_query(monkeypatch):
    monkeypatch.setattr(contrib_sync, "CONTRIB_AVAILABLE", True)
    monkeypatch.setattr(contrib_sync, "run_contrib_core_sync", lambda **kwargs: {})
    monkeypatch.setattr(contrib_sync, "run_contrib_extended_sync", lambda **kwargs: {})
    monkeypatch.setattr(
        contrib_sync,
        "_cloud_query_rows",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("an empty filtered scope must not execute the cable NQE")
        ),
    )
    monkeypatch.setattr(
        contrib_sync,
        "run_contrib_cable_sync",
        lambda *, cable_rows, **kwargs: {"received": len(cable_rows)},
    )

    result = contrib_sync.run_contrib_full_sync(
        source_records={"devices": []},
        profile=SimpleNamespace(),
        dryrun=True,
        client=object(),
        network_id="network-fixture",
        include_cloud=False,
        include_cables=True,
        filtered_scope=True,
        job=SimpleNamespace(),
    )

    assert result["cables"] == {"received": 0}


def test_auxiliary_query_falls_back_to_bundled_inline_async():
    class _Client:
        def __init__(self):
            self.modes = []

        def run_nqe_query(self, *, query_spec, **_kwargs):
            self.modes.append(query_spec.execution_mode)
            if query_spec.execution_mode == "query_path":
                raise ForwardClientError("not published")
            assert "@contract-version" in query_spec.query_text
            return [{"account_id": "fixture-account"}]

    client = _Client()

    rows = contrib_sync._cloud_query_rows(
        client,
        "network-fixture",
        "snapshot-fixture",
        "forward_cloud_accounts.nqe",
    )

    assert rows == [{"account_id": "fixture-account"}]
    assert client.modes == ["query_path", "query"]
