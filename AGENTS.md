# Forward Nautobot Scaffold Agent Guide

This repo is the starting point for a Forward Networks plugin for Nautobot.

## Start Here

- Read `ARCHITECTURE.md` before changing code.
- Keep repo knowledge in `docs/00_Project_Knowledge/`.
- Track non-trivial work in `docs/03_Plans/active/`.

## Boundaries

- `forward_nautobot/__init__.py` owns plugin metadata.
- `forward_nautobot/integrations/forward/` owns Forward-specific client and sync scaffolding.
- `forward_nautobot/jobs.py` is the Nautobot job entrypoint.
- `forward_nautobot/views.py` and `forward_nautobot/urls.py` are the plugin UI surface.

## Working Rules

- Keep the scaffold small and legible.
- Prefer explicit doc files over hidden tribal knowledge.
- Add or update tests for importability and metadata whenever you add a new boundary.
- Do not add real credentials, tenant IDs, network IDs, or snapshots.
- Preserve raw NQE contract fields in Python; if a field shape needs to change, move the reshape into NQE instead of normalizing in code.
- Treat support-bundle and issue-reporting surfaces as first-class work once the sync path exists.
- Add ingestion tests against a sanitized fixture dataset only after the Nautobot write path and query contracts are stable.
