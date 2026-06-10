# Forward Nautobot Architecture

## Goal

Build a Nautobot 3.1 plugin that mirrors the useful parts of the existing Forward integration work:

- Forward API client boundary
- query and snapshot abstractions
- Nautobot job entrypoints for sync work
- a small UI surface for configuration and execution visibility
- a model registry for the first inventory/IPAM slice

Earlier branching/sharding protection is intentionally not carried over. Nautobot will use preview/sync jobs, DiffSync adapters, and API-level pagination/retry protection instead.

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
- Prefer tiny stubs that explain intent over large unverified abstractions.
- Make the first working surfaces importable and testable before adding depth.
- Keep contract fields unnormalized: if a field shape needs to change, do it in NQE so the Python side can carry the raw contract through unchanged.

## Current Boundaries

- `forward_nautobot/integrations/forward/client.py` owns API transport, snapshots, query lookup, and NQE execution.
- `forward_nautobot/integrations/forward/runner.py` turns a `ForwardSyncSpec` into a report for jobs/UI.
- `forward_nautobot/integrations/forward/adapters.py` holds the raw source store and the planned Nautobot write store.
- `forward_nautobot/integrations/forward/planner.py` turns bundled NQE rows into a raw ingestion plan across selected slices.
- `forward_nautobot/integrations/forward/support.py` turns a report into a sanitized support bundle with raw row samples and adapter summaries.
- `forward_nautobot/integrations/forward/registry.py` defines the first model slices and the expected Forward query filenames.
- `forward_nautobot/integrations/forward/jobs.py` owns Nautobot job inputs, registration, and the ingestion-plan entrypoint.

## Next Boundaries

1. DiffSync model classes for the core inventory/IPAM slice.
2. Real Nautobot object writes in the sync runner.
3. Persistent source/config records and a proper UI form flow.
4. Query files and contract tests for the model registry.
5. Support-bundle capture and issue-reporting surfaces for user diagnostics.
6. Sanitized fixture dataset ingestion tests once the write path and query contracts are in place.
