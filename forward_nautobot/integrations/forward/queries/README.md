# Forward query bundle

This directory holds the bundled Forward NQE filenames used by the registry.
Each bundled contract query declares its contract version in the file header.

Current files:

- `forward_cables.nqe`
- `forward_cloud_accounts.nqe`
- `forward_cloud_networks.nqe`
- `forward_cloud_services.nqe`
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
Every saved query is unparameterized and declares `@primaryKey`, which is required for
snapshot-to-snapshot `nqe-diffs`. The planner builds the selected device set from the current
device result and applies exact-set manufacturer, functional-class, and model filters after
full or diff execution. Direct device-backed rows expose `device`; shared rows expose the raw
`scope_devices` contributor list without reshaping it in Python.

Cloud queries are also unparameterized. Runtime loads current account membership, applies
cloud-type and account-ID filters in Python, and uses cloud-type/account-qualified primary keys
for accounts and child resources. Saved cloud-query diffs decide whether a complete current cloud
source needs to be hydrated for native Nautobot DiffSync.

The prefix queries are deliberately compact and do not expose `scope_devices`: grouping large
route tables by contributing device can exceed Forward's result-group limit. They run normally
without device filters and fail closed (zero accepted rows) during a filtered sync.

Runtime full queries use async query-ID execution. Once a profile has both a previous processed
snapshot and the same persisted scope fingerprint, changed snapshots use `nqe-diffs`. Diff
failure is attributed to the slice and is never silently replaced by a full query.

If a bundled path is not saved, runtime submits the packaged source inline through the async
execution API after removing only the saved-query `@primaryKey` annotation. That keeps the
plugin usable before publication, but the inline slice is not eligible for `nqe-diffs` until it
has a committed query ID.

The bundle can be added, updated, committed, and audited with
`nautobot-server forward_publish_queries`. Source parity is checked against concrete committed
source, not merely query path or head metadata.
