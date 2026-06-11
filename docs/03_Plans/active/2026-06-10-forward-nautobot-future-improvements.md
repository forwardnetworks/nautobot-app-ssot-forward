# Forward Nautobot Future Improvements

## Purpose

Capture the next set of improvements after the current tranche is complete.

These items are intentionally lower priority than the current contract, support, and CI hardening work. They are the right place for follow-on ergonomics and deeper operational polish.

## Status

Implemented. The follow-on ideas now live in the other active planning notes and are not blocking this tranche.

## Suggested Order

1. Persist profile status and run history.
   - Store last successful run, last failure, and last support bundle metadata with the connection profile.
   - Surface that history in the UI instead of only showing the current in-memory summary.

2. Expand support-bundle controls.
   - Add a stronger allowlist/denylist model for redaction.
   - Support operator-selected sharing profiles for internal versus external reports.

3. Add a contract diff report.
   - Compare the current bundled query contract against the previous release.
   - Publish the diff as an artifact so contract drift is visible without digging through CI logs.

4. Add release automation for tagged builds.
   - Publish the wheel and source distribution only when the tag matches the package version.
   - Keep the release state check wired into the publishing workflow.

5. Expand sanitized fixture coverage.
   - Add more representative rows only after the current slice set stays stable.
   - Keep the fixture payloads raw and customer-neutral.

6. Improve profile editing ergonomics.
   - Provide a clearer profile edit form and status summary in the plugin UI.
   - Keep the screen read-only unless the user is intentionally changing configuration.

## Out Of Scope For The Last Tranche

- Adding new model slices
- Changing the raw contract shape without a matching NQE change
- Customer-specific documentation
- Broad UI redesign unrelated to profile and policy visibility

## Notes

- Keep the Python layer raw.
- Keep NQE as the contract-shaping layer.
- Favor direct evidence and explicit policy over inferred behavior.
- Use this note for ideas that should not block the current tranche from shipping.
