# Forward Networks SSoT Architecture

## Goal

Build a Nautobot 3.1 SSoT integration that syncs Forward Networks data into Nautobot through the
`nautobot-ssot` framework:

- Forward API client boundary
- query and snapshot abstractions
- Nautobot SSoT `DataSource` entrypoint for sync work
- a small UI surface for configuration and execution visibility
- a model registry for the first inventory/IPAM slice

Earlier branching/sharding protection is intentionally not carried over. Nautobot will use the SSoT
job lifecycle, DiffSync adapters, API-level pagination/retry protection, and explicit dry-run gates
instead.

## Current Shape

```text
forward_nautobot/
  __init__.py
  jobs.py
  views.py
  urls.py
  integrations/
    forward/
      client.py
      adapters.py
      models.py
      registry.py
      runner.py
      jobs.py
      queries/
```

## Principles

- Keep the repo as the system of record.
- Put integration boundaries in code, not in chat.
- Prefer small helper functions that explain intent over large unverified abstractions.
- Make the first working surfaces importable and testable before adding depth.
- Keep contract fields unnormalized: if a field shape needs to change, do it in NQE so the Python side can carry the raw contract through unchanged.

## Current Boundaries

- `forward_nautobot/integrations/forward/client.py` owns API transport, snapshots, query lookup, and NQE execution.
- `forward_nautobot/integrations/forward/runner.py` turns a `ForwardSyncSpec` into a report for jobs/UI.
- `forward_nautobot/integrations/forward/adapters.py` holds the raw source store and the planned Nautobot write store.
- `forward_nautobot/integrations/forward/planner.py` turns bundled NQE rows into a raw ingestion plan across selected slices.
- `forward_nautobot/integrations/forward/support.py` turns a report into a sanitized support bundle with raw row samples and adapter summaries.
- `forward_nautobot/integrations/forward/registry.py` defines the first model slices and the expected Forward query filenames.
- `forward_nautobot/integrations/forward/jobs.py` owns Nautobot job inputs, SSoT `DataSource`
  registration, and the ingestion-plan entrypoint.
- Support-bundle capture remains part of the sync path so operators can share sanitized evidence
  when an ingestion run fails.

## SSoT Pivot

The primary sync surface is now `ForwardInventoryDataSource`, a `nautobot_ssot.jobs.DataSource`
wrapper. It lets the SSoT app own run history, dashboard discovery, and dry-run semantics while
reusing the existing Forward planner, write executor, and support-bundle path.

```text
ForwardInventoryDataSource
  -> ForwardIngestionPlanner
     -> ForwardClient
     -> ForwardSourceAdapter
     -> NautobotTargetAdapter
     -> ForwardWritePlanner
  -> ForwardNautobotWriteExecutor only when SSoT dryrun is false
  -> support bundle pair
  -> SSoT Sync.diff / Sync.summary
```

The only registered sync job is `ForwardInventoryDataSource`. The fixture-backed dry-run helper
remains available for diagnostics and replay.

## Next Tranche

1. Replace the planned target adapter with a deeper Nautobot adapter where it improves SSoT logs and object lookup.
2. Expand object lookup coverage for any additional Nautobot object types introduced by future slices.
3. Expand ingestion tests around the SSoT job surface.
