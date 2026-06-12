# Forward Networks SSoT for Nautobot

Nautobot 3.1 SSoT app integration for syncing Forward Networks data into Nautobot.
Target platform: Nautobot 3.1.

## What Exists Now

- Nautobot app metadata for the `forward_nautobot` import package
- Python distribution metadata for `nautobot-app-ssot-forward`
- SSoT `DataSource` job for Forward Networks inventory
- SSoT dashboard data mappings for the bundled Forward model slices
- Forward API client with snapshot, query, and pagination support
- Query identity resolution that binds repository-path queries to live query IDs and commit IDs before execution
- Forward sync runner that resolves query refs and returns a sync report
- Forward connection profile for persistent plugin configuration
- Persistent SSoT profile selection for the sync job
- Write-prerequisite fields in the connection profile for the first Nautobot objects
- Editable profile form for the plugin UI
- Operational overview, status, and configuration pages for UI-first setup
- Diagnostics page plus per-slice drilldowns for the packaged fixture
- Ingestion coverage panel with per-slice row counts and drilldowns
- Packaged profile seed command plus bundled fixture data for validation and support
- Delete-policy support for missing-row handling
- Support-bundle helper that preserves raw sample rows, adapter summaries, and failure classification for troubleshooting
- Support-bundle redaction helper for safe sharing
- Support-bundle replay inputs that keep raw query references, resolved identity, and sample rows available for diagnostics
- Raw source/target adapter layer that keeps NQE fields untouched
- Raw ingestion planner that loads bundled NQE outputs into the adapter stores
- Raw write-plan layer that surfaces create/update/no-change intent before Nautobot persistence exists
- Nautobot write executor for the first core slices behind the SSoT dry-run toggle
- Safe-delete reconciliation for the first supported slices when `delete_policy` is `delete` or `mark_inactive`
- Bundled core NQE queries tagged with an explicit contract version
- Bundled query contract drift checks in tests and CI
- Sanitized fixture ingestion tests that exercise the raw adapter contract without live credentials
- Fixture-backed dry-run helper for local troubleshooting of raw Forward payloads
- Native `forward_dry_run` management command for replaying saved payloads
- Nautobot job entrypoint for the SSoT sync path
- Read-only configuration/status surface for profile readiness and current policy
- UI-first setup flow: create or edit a profile in Configuration, then run the SSoT job with that saved profile
- Fixture-backed dry-run helper for bundled NQE validation and support bundles
- Query contract and query identity checks in tests and CI
- CI gates for query contracts, wheel contents, and release/tag state
- Minimal UI and URL surfaces
- Repo docs for architecture and planning
- Tests for client, runner, jobs, and package wiring
- Live ingestion tests for the corrected Forward network when `FORWARD_LIVE_*` env vars are present
- GitHub Actions CI for tests plus wheel build

## Future Enhancements

- [`docs/03_Plans/active/2026-06-11-forward-nautobot-future-improvements.md`](docs/03_Plans/active/2026-06-11-forward-nautobot-future-improvements.md)
- future slice/object lookup expansion
- broader replay tooling and support-bundle ergonomics
- continued query-load reduction, query identity hardening, query-ID-backed diff execution, and target-state fidelity improvements

## Replay Walkthrough

1. Seed the profile and fixture data:
   `nautobot-server forward_fixture_seed`
2. Open the plugin overview to show the supported slices, ingestion coverage matrix, and query-ID diff positioning.
3. Open the diagnostics page to show readiness, coverage, status, and raw packaged rows.
4. Open a slice drilldown from the coverage matrix to show raw packaged rows.
5. Open the status page to show readiness, policy, and the profile summary.
6. Open the configuration page to show the editable profile form and saved defaults.
7. Run the SSoT job with the saved profile selected.
8. If you want a reproducible replay artifact, run the fixture-backed dry run command against `forward_nautobot/fixtures/forward_sample_ingestion.json` and use `--output` plus `--shared-output` to save the full and redacted JSON artifacts.

## Repo Map

```text
ARCHITECTURE.md
AGENTS.md
docs/
forward_nautobot/
tests/
```
