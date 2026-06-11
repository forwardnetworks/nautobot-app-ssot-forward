# Forward Nautobot Next Steps

## Goal

Turn the current Forward Nautobot implementation into a maintainable sync plugin with real Nautobot writes, stable Forward contract coverage, and release-ready operational surfaces.

## Principles

- Keep the Python layer raw: fields from Forward should stay unnormalized unless NQE itself reshapes them.
- Treat NQE as the contract-shaping layer for Forward output.
- Prefer small, explicit slices over broad speculative model coverage.
- Add supportability and release hygiene as first-class features, not afterthoughts.

## Now

1. Implement the first real Nautobot write path.
   - Map the core slices into Nautobot models.
   - Preserve exact source identity and field shapes.
   - Make preview versus sync behavior explicit.

2. Add persistent plugin configuration.
   - Store base URL, auth, network, snapshot preference, and enabled slices.
   - Make the UI editable instead of relying only on job parameters.

3. Publish contract-stable NQE for the core slices.
   - Keep field shaping in NQE.
   - Version the queries so the plugin can track contract drift.
   - Add tests that assert the exact returned fields.

4. Keep fixture ingestion coverage ahead of live-only validation.
   - Use a sanitized fixture dataset for core slices.
   - Keep the fixture boundary raw and representative.

Implemented so far:

- persistent Forward connection profile
- write-prerequisite fields for the first Nautobot objects in the connection profile
- editable profile form for the plugin UI
- delete-policy handling for missing-row behavior, now enforced for the first supported slices
- explicit contract version markers on the core bundled NQE files
- raw write plan that surfaces create/update/no-change intent
- Nautobot write executor for the first core slices behind an opt-in apply flag
- expanded Nautobot write executor coverage for `interfaces`, `vlans`, `vrfs`, `ipv4_prefixes`, `ipv6_prefixes`, `ip_addresses`, `inventory_items`, and `modules`
- contract-shaped bundled NQE for the full current slice set
- sanitized fixture ingestion coverage for the raw adapter boundary
- fixture-backed dry-run helper for local troubleshooting
- native dry-run management command for replaying saved payloads
- support-bundle failure classification for configuration versus row blockers

## Completed Next

The original next-step items are now reflected in the implementation:

- full write coverage for the current slice set
- explicit missing-row handling and visible update intent in the write plan and support bundle
- richer support bundle diagnostics, including query reference, snapshot metadata, sample rows, diff summary, and failure classification
- a native dry-run command surface for troubleshooting saved payloads

## Later

1. Add broader release and CI gates.
   - import
   - build
   - fixture ingestion
   - live ingestion subset
   - wheel contents
   - GitHub tag/release state

2. Add slice-by-slice contract matrices.
   - Forward query file
   - returned fields
   - Nautobot target model
   - identity fields
   - shaping rules
   - Current draft: [`2026-06-10-forward-nautobot-contract-matrix.md`](./2026-06-10-forward-nautobot-contract-matrix.md)

3. Add broader sanitized fixture coverage as more slices are enabled.

4. Tighten operational ergonomics.
   - clearer job failure messages
   - more actionable logging
   - support for replaying recorded payloads

5. Capture extra follow-on ideas in the companion note.
   - [`2026-06-10-forward-nautobot-additional-ideas.md`](./2026-06-10-forward-nautobot-additional-ideas.md)
   - Keep the roadmap focused while still preserving the longer-term ideas.

## Suggested Order

```text
Now  -> real writes, persistent config, contract NQE, fixture coverage
Next -> broader slices, delete policy, support bundle diagnostics, dry-run surface
Later -> expanded gates, contract matrix, more fixtures, operational ergonomics
```
