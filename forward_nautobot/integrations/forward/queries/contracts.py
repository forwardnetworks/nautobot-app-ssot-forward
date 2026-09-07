"""Bundled Forward query contract metadata."""

from __future__ import annotations

from importlib import resources
from typing import Any

from forward_sdk.nqe.files import select_field_sets

from ..registry import CORE_MODEL_MAPPINGS

QUERY_CONTRACT_FIELDS: dict[str, tuple[str, ...]] = {
    "forward_locations.nqe": ("name", "city", "country", "scope_devices"),
    "forward_platforms.nqe": ("name", "manufacturer", "scope_devices"),
    "forward_device_types.nqe": ("manufacturer", "name", "color", "scope_devices"),
    "forward_devices.nqe": (
        "name",
        "location",
        "vendor",
        "device_type",
        "model",
        "platform",
    ),
    "forward_interfaces.nqe": (
        "device",
        "name",
        "type",
        "lag",
        "mode",
        "untagged_vlan",
        "enabled",
        "mtu",
        "description",
        "speed",
        "mac_address",
    ),
    "forward_vlans.nqe": ("site", "vid", "name", "status", "scope_devices"),
    "forward_vrfs.nqe": (
        "name",
        "rd",
        "description",
        "enforce_unique",
        "scope_devices",
    ),
    "forward_prefixes_ipv4.nqe": ("vrf", "prefix", "status"),
    "forward_prefixes_ipv6.nqe": ("vrf", "prefix", "status"),
    "forward_ip_addresses.nqe": (
        "device",
        "interface",
        "vrf",
        "address",
        "host_ip",
        "prefix_length",
        "status",
    ),
    "forward_inventory_items.nqe": (
        "device",
        "manufacturer",
        "name",
        "label",
        "part_id",
        "serial",
        "asset_tag",
        "role",
        "status",
        "discovered",
        "description",
    ),
    "forward_modules.nqe": (
        "device",
        "module_bay",
        "manufacturer",
        "model",
        "part_number",
        "status",
        "serial",
        "asset_tag",
        "description",
    ),
    "forward_cables.nqe": (
        "device",
        "interface",
        "remote_device",
        "remote_interface",
        "status",
    ),
    "forward_cloud_accounts.nqe": ("account_id", "name", "cloud_type"),
    "forward_cloud_networks.nqe": (
        "account_id",
        "cloud_type",
        "network_id",
        "name",
        "parent_id",
        "kind",
        "cidrs",
    ),
    "forward_cloud_services.nqe": (
        "account_id",
        "cloud_type",
        "service_id",
        "name",
        "vpc_id",
        "service_kind",
    ),
}


def get_query_contract_field_sets(filename: str) -> tuple[tuple[str, ...], ...]:
    """Return the field sets each ``select`` block in the bundled query produces.

    Parsing is owned by ``forward_sdk.nqe.files.select_field_sets``; this wrapper
    only resolves the packaged file. Verified byte-identical to the previous
    hand-rolled parser across every bundled query.
    """
    package_root = resources.files("forward_nautobot.integrations.forward.queries")
    contents = (package_root / filename).read_text(encoding="utf-8")
    return select_field_sets(contents)


def get_query_contract_fields(filename: str) -> tuple[str, ...]:
    expected = QUERY_CONTRACT_FIELDS[filename]
    field_sets = get_query_contract_field_sets(filename)
    return expected if expected in field_sets else ()


def get_bundled_query_contracts() -> dict[str, dict[str, Any]]:
    return {
        filename: {
            "fields": QUERY_CONTRACT_FIELDS[filename],
            "field_sets": get_query_contract_field_sets(filename),
            "contract_version": next(
                (
                    mapping.contract_version
                    for mapping in CORE_MODEL_MAPPINGS
                    if mapping.forward_query_file == filename
                ),
                "",
            ),
        }
        for filename in sorted(QUERY_CONTRACT_FIELDS)
    }
