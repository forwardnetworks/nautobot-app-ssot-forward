# Forward query bundle

This directory holds the bundled Forward NQE filenames used by the registry.
Each bundled contract query declares its contract version in the file header.

Current files:

- `forward_locations.nqe`
- `forward_platforms.nqe`
- `forward_device_types.nqe`
- `forward_devices.nqe`
- `forward_interfaces.nqe`
- `forward_vlans.nqe`
- `forward_vrfs.nqe`
- `forward_prefixes_ipv4.nqe`
- `forward_prefixes_ipv6.nqe`
- `forward_ip_addresses.nqe`
- `forward_inventory_items.nqe`
- `forward_modules.nqe`

All bundled files now carry contract-shaped query bodies and explicit contract-version headers.
The registry and executor use the same slice order so the Python layer stays thin and raw.
