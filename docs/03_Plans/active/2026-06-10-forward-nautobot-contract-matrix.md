# Forward Nautobot Contract Matrix

## Scope

This matrix tracks the current bundled Forward contract surface and the Nautobot target shape we are aiming at.

## Core Slices

| Slice | Query File | Current Forward Fields | Nautobot Target | Write Notes |
| --- | --- | --- | --- | --- |
| `locations` | `forward_locations.nqe` | `name`, `city`, `country` | `dcim.Location` | Written through the executor with profile-supplied `location_type` and `status` defaults. |
| `platforms` | `forward_platforms.nqe` | `name`, `manufacturer`, `device_type` | `dcim.Platform` | Written through the executor with manufacturer lookup/upsert. |
| `device_types` | `forward_device_types.nqe` | `name`, `manufacturer`, `model`, `slug` | `dcim.DeviceType` | Written through the executor with manufacturer lookup and slug derivation. |
| `devices` | `forward_devices.nqe` | `name`, `location`, `vendor`, `model`, `device_type` | `dcim.Device` | Written through the executor with explicit location, platform, device type, role, and status resolution. |
| `interfaces` | `forward_interfaces.nqe` | `device`, `name`, `type`, `lag`, `mode`, `untagged_vlan`, `enabled`, `mtu`, `description`, `speed` | `dcim.Interface` | Written through the executor with device lookup and optional LAG linkage. |
| `vlans` | `forward_vlans.nqe` | `site`, `vid`, `name`, `status` | `ipam.VLAN` | Written through the executor with explicit location lookup. |
| `vrfs` | `forward_vrfs.nqe` | `name`, `rd`, `description`, `enforce_unique` | `ipam.VRF` | Written through the executor with direct field synchronization. |
| `ipv4_prefixes` | `forward_prefixes_ipv4.nqe` | `vrf`, `prefix`, `status` | `ipam.Prefix` | Written through the executor with VRF and status resolution. |
| `ipv6_prefixes` | `forward_prefixes_ipv6.nqe` | `vrf`, `prefix`, `status` | `ipam.Prefix` | Written through the executor with VRF and status resolution. |
| `ip_addresses` | `forward_ip_addresses.nqe` | `device`, `interface`, `vrf`, `address`, `host_ip`, `prefix_length`, `status` | `ipam.IPAddress` | Written through the executor with device/interface assignment and optional VRF linkage. |
| `inventory_items` | `forward_inventory_items.nqe` | `device`, `manufacturer`, `name`, `label`, `part_id`, `serial`, `asset_tag`, `role`, `status`, `discovered`, `description` | `dcim.InventoryItem` | Written through the executor with device lookup, manufacturer lookup, and explicit role/status handling. |
| `modules` | `forward_modules.nqe` | `device`, `module_bay`, `manufacturer`, `model`, `part_number`, `status`, `serial`, `asset_tag`, `description` | `dcim.Module` | Written through the executor with module bay resolution, module type lookup, and status handling. |

## Supporting Configuration

| Field | Purpose | Status |
| --- | --- | --- |
| `default_location_type_name` | Required `Location` dependency for write readiness | Scaffolded in the profile model and form |
| `default_location_status_name` | Required `Location` dependency for write readiness | Scaffolded in the profile model and form |
| `default_device_role_name` | Required `Device` dependency for write readiness | Scaffolded in the profile model and form |
| `default_device_status_name` | Required `Device` dependency for write readiness | Scaffolded in the profile model and form |
| `delete_policy` | Missing-row handling policy for the write path | Scaffolded in the profile model and form and enforced for the first supported slices |

## Expansion Order

1. Stabilize the full current slice set above with contract tests and fixture coverage.
2. Add broader release and CI gates around the bundled contract and build artifact.

## Notes

- Keep field shaping in NQE rather than normalizing rows in Python.
- Treat missing write prerequisites as configuration issues, not silent fallbacks.
- Update this matrix whenever a query contract, model field contract, or write policy changes.
