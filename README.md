# Forward Networks SSoT for Nautobot

Nautobot 3.1 SSoT app integration for syncing Forward Networks data into Nautobot.
Target platform: Nautobot 3.1.

## What Exists Now

- Nautobot app metadata for the `forward_nautobot` import package
- Python distribution metadata for `nautobot-app-ssot-forward`
- SSoT `DataSource` job for Forward Networks inventory
- SSoT dashboard data mappings for the bundled Forward model slices
- Forward API client with snapshot, query, and pagination support
- Forward sync runner that resolves query refs and returns a sync report
- Forward connection profile for persistent plugin configuration
- Persistent SSoT profile selection for the sync job
- Write-prerequisite fields in the connection profile for the first Nautobot objects
- Editable profile form for the plugin UI
- Delete-policy support for missing-row handling
- Support-bundle helper that preserves raw sample rows, adapter summaries, and failure classification for troubleshooting
- Support-bundle redaction helper for safe sharing
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
- Fixture-backed dry-run helper for bundled NQE validation and support bundles
- CI gates for query contracts, wheel contents, and release/tag state
- Minimal UI and URL surfaces
- Repo docs for architecture and planning
- Tests for client, runner, jobs, and package wiring
- Live ingestion tests for the corrected Forward network when `FORWARD_LIVE_*` env vars are present
- GitHub Actions CI for tests plus wheel build

## Future Enhancements

- deeper use of `nautobot_ssot.contrib.adapter.NautobotAdapter` once the write model matures
- broader replay tooling for future slice drift

## Repo Map

```text
ARCHITECTURE.md
AGENTS.md
docs/
forward_nautobot/
tests/
```
