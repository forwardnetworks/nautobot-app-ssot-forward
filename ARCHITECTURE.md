# Forward Networks SSoT Architecture

## Goal

Build a Nautobot 3.1 SSoT integration that syncs Forward Networks data into Nautobot through the
`nautobot-ssot` framework:

- Forward API client boundary
- query and snapshot abstractions
- Nautobot SSoT `DataSource` entrypoint for sync work
- a small UI surface for configuration and execution visibility
- an operational UI with overview, status, configuration, diagnostics, and slice-detail pages
- a model registry for the first inventory/IPAM slice

Earlier branching/sharding protection is intentionally not carried over. Nautobot will use the SSoT
job lifecycle, DiffSync adapters, API-level pagination/retry protection, and explicit dry-run gates
instead.

## Current Shape

```text
forward_nautobot/
  __init__.py
  fixture_support.py
  jobs.py
  views.py
  urls.py
  fixtures/
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

## Portable Hardening

The most useful hardening patterns for this repo are contractual rather than platform-specific:

- Query identity is a contract. Inline NQE remains valid for simple runs, but repository-path and direct query-ID runs should resolve and record the live query ID and commit ID before execution, and use `nqe-diffs` whenever the snapshot pair is available.
- Bundled query sources should stay versioned and drift-checked in CI so query shape changes are visible before release.
- Support bundles should remain the canonical troubleshooting artifact, with both the full payload and a redacted shareable view.
- Replay tooling should be able to rebuild a dry run from a saved fixture or exported bundle without requiring live credentials.
- Request pressure should stay bounded through explicit parameters, caching, conservative pagination behavior, and dependent query scoping when parent keys are already known.
- Release gates should keep checking contract drift, wheel contents, release/tag state, and sensitive-content hygiene.
- The SSoT job lifecycle already covers run history, so there is no separate orchestration layer to recreate here.

## Current Boundaries

- `forward_nautobot/integrations/forward/client.py` owns API transport, snapshots, query lookup, and NQE execution.
- `forward_nautobot/integrations/forward/runner.py` turns a `ForwardSyncSpec` into a report for jobs/UI.
- `forward_nautobot/integrations/forward/adapters.py` holds the raw source store and the planned Nautobot write store.
- `forward_nautobot/integrations/forward/planner.py` turns bundled NQE rows into a raw ingestion plan across selected slices and injects child-slice scope parameters from already loaded parent rows.
- `forward_nautobot/integrations/forward/support.py` turns a report into a sanitized support bundle with raw row samples and adapter summaries.
- `forward_nautobot/integrations/forward/registry.py` defines the first model slices and the expected Forward query filenames.
- `forward_nautobot/integrations/forward/jobs.py` owns Nautobot job inputs, SSoT `DataSource`
  registration, and the sync job entrypoint.
- `forward_nautobot/fixture_support.py` owns the canonical seeded profile and packaged fixture lookup.
- Support-bundle capture remains part of the sync path so operators can share sanitized evidence
  when an ingestion run fails.

## SSoT Pivot

The primary sync surface is now `ForwardInventoryDataSource`, a `nautobot_ssot.jobs.DataSource`
wrapper. It lets the SSoT app own run history, dashboard discovery, and dry-run semantics while
reusing the existing Forward planner, write executor, and support-bundle path.

The UI setup path is intentionally simple:

1. Create or update a saved connection profile in the Configuration page.
2. Review the Overview or Status page for readiness, supported slices, and the last snapshot
   baseline.
3. Run the SSoT job with the saved profile selected.
4. Use the support bundle and redacted shareable output if an issue needs to be reported.

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

1. Expand object lookup coverage for any additional Nautobot object types introduced by future slices.
2. Expand ingestion tests around the SSoT job surface.
3. Use [`docs/03_Plans/active/2026-06-11-forward-nautobot-full-model-coverage-plan.md`](docs/03_Plans/active/2026-06-11-forward-nautobot-full-model-coverage-plan.md) as the implementation roadmap for broader model support.
4. Follow the hardening order in [`docs/03_Plans/active/2026-06-11-forward-nautobot-future-improvements.md`](docs/03_Plans/active/2026-06-11-forward-nautobot-future-improvements.md).
