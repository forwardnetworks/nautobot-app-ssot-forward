# Forward Nautobot Additional Ideas

## Purpose

Capture the follow-on work that would make this plugin safer to operate, easier to debug, and better aligned with how Forward should shape and emit contract data.

## What I Would Do Next

1. Make write readiness explicit per slice.
   - Keep required Nautobot defaults in the connection profile.
   - Surface blockers in job output and support bundles.
   - Avoid silent fallbacks when the write path is not actually ready.

2. Publish contract-shaped NQE for every writeable slice.
   - Keep field shaping in NQE, not in Python.
   - Version each query contract so drift is visible.
   - Add field-assertion tests for the exact emitted contract.

3. Add a replayable dry-run and support bundle trail.
   - Preserve raw sample rows, query refs, and snapshot metadata.
   - Store enough context to reproduce a failure without live credentials.
   - Keep the summary human-readable and the payloads machine-readable.

4. Add safe write semantics before expanding slice coverage.
   - Treat missing rows with an explicit policy.
   - Make create, update, deactivate, and delete behavior visible in the plan.
   - Require idempotent matching rules before allowing real writes.

5. Expand the slice set in a controlled order.
   - `locations`
   - `platforms`
   - `device_types`
   - `devices`
   - `interfaces`
   - `vlans`
   - `vrfs`
   - `ipv4_prefixes`
   - `ipv6_prefixes`
   - `ip_addresses`
   - `inventory_items`
   - `modules`

6. Tighten release and CI gates around the actual contract.
   - import
   - build
   - sanitized fixture ingestion
   - live subset ingestion
   - wheel contents
   - tag/release state

## Nautobot Capabilities To Lean On

| Area | What to Use | Why It Matters |
| --- | --- | --- |
| Plugin config | Persistent settings model plus editable form | Keeps source defaults in one place and avoids job-parameter drift |
| Jobs | Dry-run, ingest, replay, and support-bundle jobs | Makes operations explicit and repeatable |
| Statuses and choices | Native status fields for write state and blockers | Gives users a standard way to see readiness and lifecycle |
| Object change logging | Existing audit trail for writes | Makes it easier to trace what changed and when |
| Custom views | Profile status, last ingest, last support bundle | Gives operators a quick control surface without opening a job form |
| Custom links | Jump from Nautobot objects to source evidence | Improves troubleshooting without duplicating source data |
| Validation hooks | Early rejection for malformed or incomplete config | Moves errors closer to the user and keeps job runs cleaner |

## Forward Output To Strengthen

| Area | What to Emit from NQE | Why It Helps |
| --- | --- | --- |
| Identity | Stable source identifiers and matching keys | Keeps Nautobot matching deterministic |
| Contract versioning | Explicit version markers per query | Makes drift and breaking changes visible |
| Readiness hints | Fields that signal whether a row can be written safely | Avoids hidden Python-side guesswork |
| Diagnostics | Query metadata, snapshot metadata, and source references | Makes support bundles more useful |
| Contract shape | Final field names and data types | Keeps the Python side as a pass-through layer |
| Write policy hints | Source-side flags for keep, deactivate, or delete intent | Reduces ambiguity before the plan reaches Nautobot |
| Incremental state | Stable row keys and source timestamps | Opens the door to better replay and future delta handling |

## Operational Guardrails

| Area | Suggested Guardrail | Why It Matters |
| --- | --- | --- |
| Matching | Keep identity rules explicit per slice | Prevents accidental cross-object reuse |
| Deletes | Require an explicit policy and make it visible | Stops silent data loss |
| Dry runs | Save raw inputs and computed plans | Lets support replay a failure exactly |
| Fixtures | Keep sanitized fixtures representative of real output | Prevents tests from drifting away from production contracts |
| CI | Gate on the actual bundled queries and build artifact | Catches packaging or contract regressions early |
| Support | Classify failures before attaching logs | Makes escalation faster and clearer |

## Extra Ideas If This Grows Further

1. Add a lightweight plugin health page.
   - Show last successful ingest, last failure, and current readiness.

2. Add a contract diff report.
   - Compare current query output against the prior contract version.
   - Fail fast when fields or types change unexpectedly.

3. Add a support bundle redaction pass.
   - Keep raw evidence available to operators.
   - Strip obvious secrets before bundles are shared externally.

4. Add replay helpers for recorded payloads.
   - Let maintainers rerun a saved snapshot without reaching the live source.

5. Expand sanitized fixture coverage slice by slice.
   - Add the next slice only after the current one has a stable contract test.

## Notes

- Keep the Python layer raw and small.
- Treat NQE as the place where contract shaping belongs.
- Prefer explicit configuration over implicit inference.
- Add one slice at a time, then prove it with fixture coverage before broadening the write path.
