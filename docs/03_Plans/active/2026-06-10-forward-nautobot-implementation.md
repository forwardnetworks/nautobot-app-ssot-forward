# Forward Nautobot Implementation Plan

## Goal

Create the first repo-shaped implementation for a Forward Networks Nautobot plugin and align it with the existing Forward integration shape.

## Scope

- package metadata
- plugin config
- Forward integration boundary
- Nautobot job entrypoint
- minimal docs
- import smoke tests
- bundled query filenames and packaging rules
- contract rules that preserve raw NQE fields without Python-side normalization

## Out of Scope

- real Forward API integration
- real Nautobot data model mapping
- production job logic
- release packaging
- query body parity with the existing query library

## Acceptance Criteria

- `forward_nautobot` imports cleanly
- plugin metadata is defined in `__init__.py`
- job registration surface exists
- docs explain the repo shape and next steps
- tests prove the plugin stays importable
- bundled query filenames are present on disk and in the wheel
- contract fields stay untouched in Python and are reshaped only in NQE when needed

## Current Status

Implemented:

- Nautobot plugin metadata and menu wiring
- Forward API client with snapshot/query helpers
- Forward sync runner and preview/sync job entrypoints
- registry of the first Nautobot model slices
- query bundle directory with contract-shaped `.nqe` files and version headers
- packaging rules for the query assets
- import, job, client, runner, and query contract tests
- contract guidance that keeps the Python side as a pass-through for NQE fields
- raw ingestion planner and ingestion-plan job for bundled NQE validation
- raw Nautobot write executor for the first supported slices
- fixture-backed dry-run support for local troubleshooting
- support-bundle capture and redaction helpers for safe sharing
- live ingestion tests against the corrected Forward network
- release and CI gates for build, wheel contents, query contracts, release state, and sensitive content
- sanitized fixture ingestion test coverage for the raw adapter boundary

Verified:

- `./.venv/bin/python -m pytest -q`
- `./.venv/bin/python -m build`
- `./.venv/bin/python scripts/check_harness.py`
- `./.venv/bin/python scripts/check_query_contracts.py`
- `./.venv/bin/python scripts/check_wheel_contents.py`
- `./.venv/bin/python scripts/check_release_state.py`
- `./.venv/bin/python scripts/check_sensitive_content.py --all-history`
- live Forward ingestion contract tests with `FORWARD_LIVE_*`

## Next Step

Broaden slice-by-slice contract tracking, replay tooling, and operational ergonomics as more Forward output surfaces are brought in.

## Later Milestones

- Expand the sanitized fixture dataset as more model slices are added.
- Add finer-grained release automation and drift monitoring for future slice growth.
