# Forward Networks SSoT for Nautobot

Nautobot 3.1 app for syncing Forward Networks inventory and IPAM data through
`nautobot-ssot`.

This plugin uses an SSoT job for run history, dry-run semantics, and
support-bundle capture, with support for Forward async query execution.

## Release Compatibility

| Plugin | Nautobot | nautobot-ssot | Forward | Status |
| --- | --- | --- | --- | --- |
| `0.1.1` | `3.1.x` | `4.4` - `<5.0` compatible | `26.6+` for async execution | Current |

## Overview

- Plugin metadata and app wiring under `forward_nautobot/__init__.py`
- SSoT data source entrypoint and job registration in `forward_nautobot/jobs.py`
- Forward API client with snapshot lookup, query resolution, and paging
- Query identity resolution (`query_path`/`query_id`) to a concrete runtime query ID
- Contracted query set shipped with the plugin in
  `forward_nautobot/integrations/forward/queries/*.nqe`
- Planner and adapters for raw source rows and planned Nautobot writes
- Optional dry-run mode, including support-bundle collection and replay
- Support-bundle diagnostics with safe redaction options
- Profile persistence for repeated demo/demo-friendly runs
- SSoT UI pages for overview, configuration, status, diagnostics, and slice detail
- CI gates for query contracts, wheel contents, sensitive-content checks, and release state

GitHub Actions CI runs these checks on every push and release.

## Supported Model Slices

The following model slugs are currently in the shipped scope.

| Slug | Nautobot Scope | Required Input Fields | Default | Notes |
| --- | --- | --- | --- | --- |
| `locations` | `dcim.location` | `name` | enabled | Core seed set |
| `platforms` | `dcim.platform` | `name` | enabled | Requires location scope |
| `device_types` | `dcim.devicetype` | `name` | enabled | Requires location scope |
| `devices` | `dcim.device` | `name` | enabled | Depends on `locations`, `platforms`, `device_types` |
| `interfaces` | `dcim.interface` | `device`, `name` | disabled | Depends on `devices` |
| `vlans` | `ipam.vlan` | `site`, `vid` | disabled | Depends on `locations` |
| `vrfs` | `ipam.vrf` | `name` | disabled | Depends on `devices` |
| `ipv4_prefixes` | `ipam.prefix` | `prefix`, `vrf` | disabled | Depends on `vrfs` |
| `ipv6_prefixes` | `ipam.prefix` | `prefix`, `vrf` | disabled | Depends on `vrfs` |
| `ip_addresses` | `ipam.ipaddress` | `device`, `interface`, `address`, `vrf` | disabled | Depends on `devices`,`interfaces`,`vrfs` |
| `inventory_items` | `dcim.inventoryitem` | `device`, `name` | disabled | Depends on `devices` |
| `modules` | `dcim.module` | `device`, `module_bay` | disabled | Depends on `devices` |

## Installation

### Install

From wheel or source distribution:

```bash
pip install /path/to/nautobot_app_ssot_forward-0.1.1-py3-none-any.whl
```

Install dependencies before loading in Nautobot:

```bash
pip install nautobot==3.1.* nautobot-ssot>=4.4
```

### Enable plugin

In `nautobot_config.py`:

```python
PLUGINS = [
    "forward_nautobot",
]
```

Run migrations:

```bash
nautobot-server migrate
```

Collect static and run the server as usual for your Nautobot deployment.

## First Run

1. Seed a deterministic demo profile and fixture:

   ```bash
   nautobot-server forward_fixture_seed
   ```

2. Open the plugin configuration page.
3. Confirm or create at least one saved profile with:
   - `name`, `base_url`, `username`, `password`, `network_id`
   - `snapshot_id` (default `latestProcessed`)
   - one or more model slugs in `enabled_models`
   - `query_contract_version` (default `v1`)
4. Run the Forward SSoT job and choose that profile.
5. Review the diagnostic and coverage views before applying writes.

The plugin keeps profile values in the Nautobot DB and reuses them for preview and
non-preview runs.

## Configuration Fields

The profile form includes these fields:

- `base_url` (URL)
- `username`
- `password`
- `verify_tls` (`true`/`false`, default `true`)
- `network_id`
- `snapshot_id` (`latestProcessed` or explicit snapshot ID)
- `enabled_models` (comma-separated slugs)
- `query_contract_version` (currently `v1`)
- `default_location_type_name`
- `default_location_status_name`
- `default_device_role_name`
- `default_device_status_name`
- `delete_policy` (`ignore`, `mark_inactive`, `delete`)
- `is_default`

The plugin uses `httpx` with `trust_env=True`, so environment proxy settings are
respected automatically. Configure standard `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`
variables on the Nautobot process to route Forward API traffic through enterprise
proxies when needed.

## Async NQE and Query Identity

All query execution in this branch is async where possible and resolves query
IDs before execution, which is required for Forward 26.6+ hosts that support
that transport.

- Runtime query references are resolved on demand from profile path settings.
- Live and fixture paths stay versioned and validated in CI through query-contract checks.
- Snapshot resolution supports explicit snapshot IDs and `latestProcessed`.

## Commands

### Management commands

```bash
nautobot-server forward_fixture_seed
nautobot-server forward_demo_seed
nautobot-server forward_dry_run <fixture.json> \
  --sample-size 5 \
  --sharing-profile external \
  --output /tmp/replay.json \
  --shared-output /tmp/replay-shared.json
```

## Local Validation

Unit and integration testing commands:

```bash
./.venv_local_test/bin/pytest -q
./.venv_local_test/bin/pytest -q -m "not integration"
./.venv_local_test/bin/pytest -q -m integration
```

Run live integration tests only when these are set:

- `FORWARD_LIVE_BASE_URL`
- `FORWARD_LIVE_USERNAME`
- `FORWARD_LIVE_PASSWORD`
- `FORWARD_LIVE_NETWORK_ID`
- optional `FORWARD_LIVE_VERIFY_TLS`
- optional `FORWARD_LIVE_SNAPSHOT_ID` (defaults to `latestProcessed`)
- optional `FORWARD_LIVE_ASYNC_QUERY_PATH` (defaults to `/forward_nautobot_validation/forward_devices`)

Release-style validation:

```bash
python -m build
python scripts/check_sensitive_content.py --all-history
python scripts/check_harness.py
python scripts/check_query_contracts.py
python scripts/check_wheel_contents.py
python scripts/check_release_state.py
```

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Architecture flow — end-to-end diagrams](docs/architecture-flow.md)
- [Project Knowledge](docs/00_Project_Knowledge/README.md)
- [Release/goal plans](docs/03_Plans/active/)
- [Queries](forward_nautobot/integrations/forward/queries/README.md)
- [Plugin package config](forward_nautobot/__init__.py)

## Release Readiness

Run before tag/release:

- `python -m pytest -q -m "not integration"`
- `python -m build`
- `python scripts/check_sensitive_content.py --all-history`
- `python scripts/check_harness.py`
- `python scripts/check_query_contracts.py`
- `python scripts/check_wheel_contents.py`
- `python scripts/check_release_state.py`

The live validation surface should include:

- preview/sync on `locations`
- preview/sync on `devices` with explicit `forward_location_names`

For local live-dataset work, keep credentials/snapshots out of source code and
document them only in your private environment.
