"""Bundled Forward query contract metadata."""

from __future__ import annotations

import re
from importlib import resources
from typing import Any

from ..registry import CORE_MODEL_MAPPINGS

QUERY_CONTRACT_FIELDS: dict[str, tuple[str, ...]] = {
    "forward_locations.nqe": ("name", "city", "country"),
    "forward_platforms.nqe": ("name", "manufacturer", "device_type"),
    "forward_device_types.nqe": ("name", "color"),
    "forward_devices.nqe": ("name", "location", "vendor", "model", "device_type"),
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
    ),
    "forward_vlans.nqe": ("site", "vid", "name", "status"),
    "forward_vrfs.nqe": ("name", "rd", "description", "enforce_unique"),
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
}

_SELECT_BLOCK_PATTERN = re.compile(
    r"select(?:\s+distinct)?\s*\{(?P<body>.*?)\}\s*;",
    re.IGNORECASE | re.DOTALL,
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
    return tuple(
        _contract_field_names_from_select_body(match.group("body"))
        for match in _SELECT_BLOCK_PATTERN.finditer(contents)
    )


def get_query_contract_fields(filename: str) -> tuple[str, ...]:
    expected = QUERY_CONTRACT_FIELDS[filename]
    field_sets = get_query_contract_field_sets(filename)
    if not field_sets:
        return ()
    return field_sets[0] if all(field_set == expected for field_set in field_sets) else ()


def get_bundled_query_contracts() -> dict[str, dict[str, Any]]:
    return {
        mapping.forward_query_file: {
            "fields": QUERY_CONTRACT_FIELDS[mapping.forward_query_file],
            "field_sets": get_query_contract_field_sets(mapping.forward_query_file),
            "contract_version": mapping.contract_version,
        }
        for mapping in CORE_MODEL_MAPPINGS
    }
