# Forward Nautobot Scaffold Plan

## Goal

Create the first repo-shaped scaffold for a Forward Networks Nautobot plugin and align it with the existing Forward integration shape.

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
- tests prove the scaffold stays importable
- bundled query filenames are present on disk and in the wheel
- contract fields stay untouched in Python and are reshaped only in NQE when needed

## Current Status

Implemented:

- Nautobot plugin metadata and menu wiring
- Forward API client scaffold with snapshot/query helpers
- Forward sync runner and preview/sync job entrypoints
- registry of the first Nautobot model slices
- query bundle directory with placeholder `.nqe` files
- packaging rules for the query assets
- import, job, client, runner, and query contract tests
- contract guidance that keeps the Python side as a pass-through for NQE fields
- raw ingestion planner and ingestion-plan job for bundled NQE validation
- sanitized fixture ingestion test coverage for the raw adapter boundary

Verified:

- `./.venv/bin/python -m pytest -q`
- `./.venv/bin/python -m build`

## Next Step

Build the real Nautobot write layer on top of the raw ingestion planner so the planned writes become object-level persistence instead of only contract validation.

## Later Milestones

- Publish Nautobot-specific NQE queries once the model contract is stable.
- Add ingestion tests against a sanitized fixture dataset after the write path exists.
- Expand the sanitized fixture dataset as more model slices are added.
- Bring over the support-bundle diagnostics pattern so users can report issues with useful evidence.
