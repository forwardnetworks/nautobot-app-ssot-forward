# Forward Nautobot

Nautobot 3.1 plugin for syncing Forward Networks data into Nautobot.
Target platform: Nautobot 3.1.

## What Exists Now

- Plugin metadata and Nautobot app config
- Forward API client with snapshot, query, and pagination support
- Forward sync runner that resolves query refs and returns a sync report
- Support-bundle helper that preserves raw sample rows and adapter summaries for troubleshooting
- Raw source/target adapter scaffolding that keeps NQE fields untouched
- Raw ingestion planner that loads bundled NQE outputs into the adapter stores
- Sanitized fixture ingestion tests that exercise the raw adapter contract without live credentials
- Nautobot job entrypoints for preview and sync runs
- Nautobot ingestion-plan job for bundled NQE validation and support bundles
- Minimal UI and URL stubs
- Repo docs for architecture and planning
- Tests for client, runner, jobs, and package wiring
- Live ingestion tests for the corrected Forward network when `FORWARD_LIVE_*` env vars are present
- GitHub Actions CI for tests plus wheel build

## What Is Not Built Yet

- DiffSync object writes into Nautobot core models
- full model mapping execution for every Forward query file
- real UI forms for persistent source records
- delete/safe-delete policy for the write path
- broader sanitized fixture coverage for additional model slices

## Repo Map

```text
ARCHITECTURE.md
AGENTS.md
docs/
forward_nautobot/
tests/
```
