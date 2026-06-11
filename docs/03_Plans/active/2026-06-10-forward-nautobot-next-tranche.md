# Forward Nautobot Next Tranche

## Purpose

Use the next tranche to harden the contract boundary and the operational surfaces now that the core write path is in place.

This tranche should reduce operator risk, make contract drift obvious, and improve supportability without expanding the slice set.

## Status

Implemented. The remaining follow-on ideas now live in [`2026-06-10-forward-nautobot-future-improvements.md`](./2026-06-10-forward-nautobot-future-improvements.md).

## Tranche Goal

Make the plugin safer to operate and easier to support by tightening write policy, contract validation, status visibility, and release gates.

## Recommended Order

1. Finalize per-slice write policy.
   - Decide which slices can update, deactivate, or delete.
   - Make the policy visible in the write plan and support bundle.
   - Keep the policy explicit rather than inferred.

2. Add contract drift detection.
   - Compare each bundled NQE contract against the previous version.
   - Fail fast when fields or types change unexpectedly.
   - Keep drift evidence in the repo, not only in CI logs.

3. Add a support-bundle redaction pass.
   - Keep operator bundles rich.
   - Strip obvious secrets and customer-sensitive values before external sharing.
   - Preserve the raw bundle for internal debugging when needed.

4. Add a profile/status surface in the plugin UI.
   - Show last run, write readiness, missing defaults, and delete policy.
   - Let operators inspect readiness without opening a job form.
   - Keep the UI read-only unless a change is intentional.

5. Expand tests for write semantics.
   - Cover update, no-change, delete, and deactivation behavior.
   - Cover missing readiness inputs and blocked operations.
   - Keep the tests aligned with the raw contract, not with customer-specific cases.

6. Tighten CI and release gates.
   - import
   - build
   - wheel contents
   - contract tests
   - fixture coverage
   - release/tag state

## Deliverables

| Area | Deliverable | Success Signal |
| --- | --- | --- |
| Write policy | Explicit per-slice missing-row behavior | Support bundle and plan show the chosen policy |
| Contract drift | Query diff check for bundled NQE | Unexpected field/type changes fail fast |
| Support bundle | Redaction step for shared bundles | Operators can share evidence safely |
| UI status | Profile/readiness view | Readiness is visible without a job run |
| Tests | Semantic write tests | Update/no-change/delete behavior is verified |
| CI/release | Gates for package and contract integrity | Build and contract regressions are blocked early |

## Out Of Scope

- Adding new model slices
- Reworking the raw contract shape beyond what the current slices require
- Customer-specific fixtures or customer-named documentation
- Broad UI redesign unrelated to profile/status visibility

## Acceptance Criteria

This tranche is complete when:

1. Write policy is explicit and visible.
2. Contract drift is detected by tests or build checks.
3. Support bundles can be safely shared after redaction.
4. The plugin UI exposes profile readiness and current policy.
5. Write semantics have focused tests for the current slices.
6. CI and release gates cover the packaged contract and artifact shape.

## Notes

- Keep the Python layer raw.
- Keep NQE as the contract-shaping layer.
- Do not add more slices until the current contract and support surface are stable.
- Favor direct evidence in the plan, bundle, and tests over implied behavior.
