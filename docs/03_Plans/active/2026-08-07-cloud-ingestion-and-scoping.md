# Cloud Ingestion and Scoping

## Goal

Promote Forward cloud inventory into a supported Nautobot SSoT domain with explicit cloud-only
execution, account-scoped selection, async NQE execution, saved-query NQE diffs, and safe inline
fallback when the bundled queries have not been published.

## Contracts

- Nautobot native `CloudAccount`, `CloudNetwork`, `Prefix`, and `CloudService` models are the write
  targets.
- A connection profile selects `network`, `cloud`, or `all` sync domains.
- Cloud filters are generic cloud-type and Forward account-ID allowlists. Account selection is the
  ownership boundary for child networks and services.
- Saved, unparameterized cloud queries use snapshot-to-snapshot NQE diffs when the profile scope is
  unchanged. Missing saved queries execute the packaged source inline through async NQE and use a
  full result.
- Cloud-type-qualified Forward account, network, and service IDs remain the durable identities.
  Display names remain attributes and must not be used as globally unique keys.
- Only stable-ID-suffixed native cloud objects are plugin-managed. Operator metadata is preserved,
  and mutable-name objects from the earlier preview are not adopted automatically.
- Filtered cloud runs are create/update-only. Snapshot incompleteness also suppresses destructive
  reconciliation.
- Tests and documentation use provider-neutral fixtures and contain no tenant identifiers or live
  data.

## Checklist

- [x] Add profile, form, job, migration, and scope-fingerprint fields for sync mode and cloud scope.
- [x] Add cloud query registry and planner support for async saved-query diffs and inline fallback.
- [x] Apply account membership closure to account, network, and service rows.
- [x] Use stable cloud identities and preserve display names in Nautobot-native fields.
- [x] Skip network planning and writes in cloud-only mode.
- [x] Surface cloud query modes, counts, scope, and safety state in job/support output.
- [x] Add provider-neutral unit and integration-contract tests.
- [x] Pass the complete local release gate and installed-wheel checks.
- [x] Validate live reads without committing live identifiers or enabling destructive writes.
- [x] Publish only after all local and authorized live checks pass.

## Exit Criteria

- A profile can ingest only selected cloud accounts and their related networks, prefixes, and
  services into Nautobot native cloud models.
- Published cloud queries use NQE diffs across comparable snapshots.
- Unpublished cloud queries still work inline and report that diffs are disabled.
- Cloud-only mode does not query, compare, or mutate network inventory slices.
- Filtered or incomplete snapshots cannot delete or deactivate Nautobot objects.
