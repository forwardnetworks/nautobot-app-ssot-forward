"""Bundled Forward query contract metadata."""

from __future__ import annotations

import re
from importlib import resources
from typing import Any

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

_SELECT_BLOCK_START_PATTERN = re.compile(
    r"select(?:\s+distinct)?\s*\{",
    re.IGNORECASE,
)


def _contract_field_names_from_select_body(select_body: str) -> tuple[str, ...]:
    field_names: list[str] = []
    for raw_line in select_body.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line or line.startswith("//"):
            continue
        match = re.match(r"^(?P<field>[A-Za-z_][A-Za-z0-9_]*)\s*:", line)
        if match is None:
            continue
        field_name = match.group("field").strip()
        if field_name:
            field_names.append(field_name)
    return tuple(field_names)


def get_query_contract_field_sets(filename: str) -> tuple[tuple[str, ...], ...]:
    package_root = resources.files("forward_nautobot.integrations.forward.queries")
    contents = (package_root / filename).read_text(encoding="utf-8")
    field_sets: list[tuple[str, ...]] = []
    for match in _SELECT_BLOCK_START_PATTERN.finditer(contents):
        body_start = match.end()
        depth = 1
        cursor = body_start
        while cursor < len(contents) and depth:
            character = contents[cursor]
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            cursor += 1
        if depth == 0:
            field_sets.append(_contract_field_names_from_select_body(contents[body_start : cursor - 1]))
    return tuple(field_sets)


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
