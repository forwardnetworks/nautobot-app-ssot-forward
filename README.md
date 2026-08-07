<p align="center">
  <img src="forward_nautobot/static/forward_nautobot/img/forward-field-integration.svg"
       alt="Forward Field Integration" width="340">
</p>

# Forward Field Integration

**Forward Field Integration** is a Nautobot 3.1/3.2 app that syncs Forward Networks
inventory, IPAM, and cloud data into Nautobot through `nautobot-ssot`.

It uses an SSoT job for run history, dry-run semantics, and support-bundle
capture, with support for Forward async query execution.

## Release Compatibility

| Plugin | Nautobot | nautobot-ssot | Forward | Status |
| --- | --- | --- | --- | --- |
| `0.7.0` | `3.1.8`, `3.2.2` | `4.4` - `<5.0` | `26.6+` for async execution and NQE diffs | Current |

## Overview

- Plugin metadata and app wiring under `forward_nautobot/__init__.py`
- SSoT data source entrypoint and job registration in `forward_nautobot/jobs.py`
- Forward API client with snapshot lookup, query resolution, and paging
- Persisted device-population filters applied to full-query and NQE-diff rows
- Native Nautobot cloud ingestion with cloud-only execution and account closure
- Idempotent bundled-query publication with committed-source parity checks
- Query identity resolution (`query_path`/`query_id`) to a concrete runtime query ID
- Contracted query set shipped with the plugin in
  `forward_nautobot/integrations/forward/queries/*.nqe`
- Planner and adapters for raw source rows and planned Nautobot writes
- Optional dry-run mode, including support-bundle collection and replay
- Support-bundle diagnostics with safe redaction options
- Profile persistence for repeated demo/demo-friendly runs
- SSoT UI pages for overview, configuration, status, diagnostics, and slice detail
- Local release gates for query contracts, wheel contents, sensitive-content checks, and release state

Local-only validation and publishing are intentional. No GitHub Actions or
Dependabot automation runs for this repository.

## Supported Model Slices

The following model slugs are currently in the shipped scope.

| Slug | Nautobot Scope | Required Input Fields | Default | Notes |
| --- | --- | --- | --- | --- |
| `locations` | `dcim.location` | `name` | enabled | Core seed set |
| `platforms` | `dcim.platform` | `name`, `manufacturer` | enabled | Operating-system family |
| `device_types` | `dcim.devicetype` | `manufacturer`, `name` | enabled | Hardware model |
| `devices` | `dcim.device` | `name`, `vendor`, `model`, `platform` | enabled | Depends on `locations`, `platforms`, `device_types` |
| `interfaces` | `dcim.interface` | `device`, `name` | disabled | Depends on `devices` |
| `vlans` | `ipam.vlan` | `site`, `vid` | disabled | Depends on `locations` |
| `vrfs` | `ipam.vrf` | `name` | disabled | Depends on `devices` |
| `ipv4_prefixes` | `ipam.prefix` | `prefix`, `vrf` | disabled | Depends on `vrfs` |
| `ipv6_prefixes` | `ipam.prefix` | `prefix`, `vrf` | disabled | Depends on `vrfs` |
| `ip_addresses` | `ipam.ipaddress` | `device`, `interface`, `address`, `vrf` | disabled | Depends on `devices`,`interfaces`,`vrfs` |
| `inventory_items` | `dcim.inventoryitem` | `device`, `name` | disabled | Depends on `devices` |
| `modules` | `dcim.module` | `device`, `module_bay` | disabled | Depends on `devices` |

Cloud sync writes these native Nautobot models when `sync_mode` is `cloud` or `all`:

| Forward slice | Nautobot target | Identity and relationships |
| --- | --- | --- |
| Cloud accounts | `cloud.CloudAccount` | Cloud type + Forward account ID; provider relationship |
| Cloud networks and subnets | `cloud.CloudNetwork` | Cloud type + account + network ID; parent and account-specific prefix relationships |
| Cloud services | `cloud.CloudService` | Cloud type + account + service ID; cloud-network relationship |

## Installation

### Install

From wheel or source distribution:

```bash
pip install /path/to/nautobot_app_ssot_forward-0.7.0-py3-none-any.whl
```

Install dependencies before loading in Nautobot:

```bash
pip install 'nautobot>=3.1,<3.3' 'nautobot-ssot>=4.4,<5'
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
   - `sync_mode` (`network`, `cloud`, or `all`; default `network`)
   - one or more model slugs in `enabled_models`
   - `query_contract_version` (default `v2`)
   - optional device manufacturer, functional class, and hardware-model allowlists
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
- `sync_mode` (`network`, `cloud`, or `all`; default `network`)
- `query_contract_version` (currently `v2`)
- `device_vendors` (comma-separated Forward manufacturer values)
- `device_types` (comma-separated Forward functional device-class values)
- `device_models` (comma-separated Forward hardware model strings)
- `cloud_types` (optional comma-separated cloud-type values)
- `cloud_account_ids` (optional comma-separated Forward cloud account IDs)
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

### Limiting the synced device population

Set one or more of `device_vendors`, `device_types`, or `device_models` on a saved
profile or in the SSoT job inputs. Values within one field are ORed; populated
fields are combined with AND. Matching is case-insensitive and accepts either a
rendered Forward enum value or its final token. The plugin loads the current device
membership through the bundled device query, then applies the same exact-set scope to
device rows and dependent rows returned by full queries or NQE diffs.

Filtered runs are deliberately create/update-only. They never delete or deactivate
Nautobot objects that disappear merely because the current allowlist excludes them.
A fingerprint of the selected slices and filters is persisted with the snapshot;
changing scope forces a new async full query before NQE diffs resume.

Most shared slices carry a raw `scope_devices` contributor field in their NQE contract.
The prefix queries intentionally remain compact because grouping large route tables by
device can exceed Forward's NQE result-group limit. Consequently, filtered runs fail
closed for IPv4/IPv6 prefix slices and write no prefixes; unfiltered prefix runs remain
fully supported and diff-eligible.

### Native cloud ingestion and scoping

Set `sync_mode=cloud` to query, compare, and write only native Nautobot cloud objects. Set
`sync_mode=all` to run network and cloud inventory together. The default remains `network`, so
upgrading does not unexpectedly import cloud inventory.

Use `cloud_types` as a coarse selector and `cloud_account_ids` as the tenancy boundary. Values
within each field are ORed; when both fields are populated they are combined with AND. The plugin
queries current accounts first, builds the selected account set, and then retains only networks,
subnets, prefixes, and services belonging to those accounts. Filters are applied after the
unparameterized query executes so saved queries remain eligible for NQE diffs.

Nautobot cloud names are globally unique while source display names may repeat or change. The
plugin derives the Nautobot identity from immutable account/resource IDs, keeps the source display
label in `description`, stores account IDs in `CloudAccount.account_number`, and stores
network/service IDs in `extra_config`. This prevents same-name resources in different accounts
from collapsing and prevents a rename from creating a second object. Existing operator-owned
`extra_config` keys are preserved. DiffSync loads only objects carrying the plugin's stable name
suffix, so unrelated native cloud inventory is outside its reconciliation target.

Cloud objects created by the earlier opt-in preview used mutable display names and do not carry
that stable ownership suffix. Version 0.7.0 does not rename or adopt those objects automatically;
review them before enabling `cloud` or `all` mode to avoid retaining both preview and stable-ID
records. The default `network` mode makes this an explicit upgrade decision.

Cloud deletion is deliberately disabled in this release. Filtered runs, incomplete snapshots,
and NQE deletion deltas remain create/update-only and report the suppressed removal evidence.

## Async NQE and Query Identity

All full-snapshot query execution uses the Forward 26.6+ async execution API.
The plugin prefers a published query path/query ID. If a bundled query is not
saved in Forward, it submits the packaged source inline through the same async API,
so publication is not a prerequisite for running a sync.

- Runtime query references are resolved on demand from repository query paths.
- Inline fallback is full-query-only because Forward NQE diffs require a query ID.
- Published bundle queries are unparameterized and primary-keyed so the Forward diff
  endpoint can compare snapshots without unsupported request parameters.
- A prior snapshot is reused only when its scope fingerprint matches; changed snapshots
  then use the NQE diff endpoint with no silent full-query fallback.
- Saved cloud-query diffs act as the change detector. A relevant create/update delta triggers
  async hydration of the complete current cloud source required by native DiffSync; an unchanged
  cloud delta avoids the larger network/service queries.
- Live and fixture paths stay versioned and validated locally through query-contract checks.
- Snapshot resolution supports explicit snapshot IDs and `latestProcessed`.

Publish the complete bundled query set and prove committed-source parity:

```bash
nautobot-server forward_publish_queries --profile <profile> --fail-on-gap
nautobot-server forward_publish_queries --profile <profile> --overwrite --fail-on-gap
nautobot-server forward_publish_queries --profile <profile> --audit-only --fail-on-gap
```

The first form adds missing queries. Existing stale queries are reported but are changed
only when `--overwrite` is explicit. Publication enables NQE diffs; it is not required
for async full syncs. A dry-run SSoT job never publishes queries.

## Commands

### Management commands

```bash
nautobot-server forward_fixture_seed
nautobot-server forward_demo_seed
nautobot-server forward_publish_queries --profile <profile> --fail-on-gap
nautobot-server forward_dry_run <fixture.json> \
  --sample-size 5 \
  --sharing-profile external \
  --output /tmp/replay.json \
  --shared-output /tmp/replay-shared.json
```

## Local Validation

Unit and integration testing commands:

```bash
python -m pytest -q -m "not integration"
NAUTOBOT_VERSION=3.1.8 docker compose -f development/docker-compose.yml up -d --build
NAUTOBOT_VERSION=3.2.2 docker compose -f development/docker-compose.yml up -d --build
python -m pytest -q -m integration
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
python scripts/ci_local.py
python -m build
python scripts/check_sensitive_content.py --all-history
python scripts/check_harness.py
python scripts/check_query_contracts.py
python scripts/check_wheel_contents.py
python scripts/check_installed_wheel.py
python scripts/check_release_state.py
```

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Architecture flow — end-to-end diagrams](docs/architecture-flow.md)
- [Project Knowledge](docs/00_Project_Knowledge/README.md)
- [Validation Matrix](docs/00_Project_Knowledge/validation-matrix.md)
- [Security Policy](SECURITY.md)
- [Release/goal plans](docs/03_Plans/active/)
- [Queries](forward_nautobot/integrations/forward/queries/README.md)
- [Plugin package config](forward_nautobot/__init__.py)

## Release Readiness

Run before tag/release:

- `python scripts/ci_local.py`
- `python -m pytest -q -m "not integration"`
- `python -m build`
- `python scripts/check_sensitive_content.py --all-history`
- `python scripts/check_harness.py`
- `python scripts/check_query_contracts.py`
- `python scripts/check_wheel_contents.py`
- `python scripts/check_installed_wheel.py`
- `python scripts/check_release_state.py`
- `python -m twine check dist/*.whl dist/*.tar.gz`

The live validation surface should include:

- preview/sync on `locations`
- async full-query execution with exact-set device scope filtering
- strict NQE diff execution across two processed snapshots
- exact committed-source audit for every bundled query

Processed snapshots with collection or processing failures are create/update-only: explicit NQE
diff deletes and missing-object delete/mark-inactive reconciliation are suppressed and explained in
the support bundle. Bundled-query publication dry-runs exact changed paths against the selected
snapshot before commit and leaves unrelated workspace drafts untouched.

For local live-dataset work, keep credentials/snapshots out of source code and
document them only in your private environment.

Local publication requires `build`, `twine`, an authenticated `gh` CLI, and PyPI
credentials supplied through the local keyring or Twine environment variables:

```bash
python scripts/release.py X.Y.Z --summary "release summary" --publish
```

The script runs the local release gate, builds the wheel and sdist, tags the
validated commit, uploads those exact local files to GitHub Releases, and then
uploads the same files to PyPI. Publishing credentials must never be added to the
repository.
