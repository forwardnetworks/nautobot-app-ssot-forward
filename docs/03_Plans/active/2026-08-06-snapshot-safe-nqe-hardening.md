# Snapshot-Safe NQE Hardening

## Goal

Make Forward ingestion safe when a processed snapshot is incomplete, follow Forward's async NQE
polling contract, validate bundled query drafts against a snapshot before commit, and prove the
published wheel works without the source checkout.

## Scope

- Suppress explicit and inferred destructive reconciliation when current snapshot metrics report
  collection or processing failures.
- Preserve create and update operations, saved-query NQE diffs, and inline async fallback.
- Honor NQE execution `Retry-After` guidance and capture bounded execution telemetry.
- Dry-run exact bundled query paths against the selected processed snapshot before committing.
- Add a disposable, source-absent installed-wheel acceptance check for both supported Nautobot
  release lines.

## Checklist

- [x] Add snapshot completeness classification and destructive reconciliation gating.
- [x] Include completeness state and suppression counts in plans, reports, and support bundles.
- [x] Honor NQE status `Retry-After` and server timeout telemetry.
- [x] Add snapshot-aware NQE library commit dry-run and plugin-owned draft cleanup.
- [x] Add installed-wheel acceptance tooling to the full local release gate.
- [x] Run focused tests, all non-live tests, packaging checks, and both Nautobot acceptance stacks.
- [x] Publish only after local validation passes.

## Next Tranche

Use validated field feedback to decide whether snapshot incompleteness should optionally fail the
entire job instead of using the safe create/update-only default.

## Exit Criteria

- Incomplete current snapshots cannot produce delete or mark-inactive mutations.
- Async polling follows the server-provided interval and records progress/timeout fields.
- Query commits cannot proceed past a failing snapshot-aware dry run.
- The exact release wheel renders the plugin HTML and API routes on Nautobot 3.1 and 3.2 without
  the repository source present.
- The repository's complete local release gate passes.
