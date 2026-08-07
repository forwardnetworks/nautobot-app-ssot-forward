# Forward-NetBox Parity Ideas + GitOps Workflows

Date: 2026-06-19
Context: Mined the sibling `forward-netbox` plugin (now at v1.6.0, tags through
v1.5.10) for transferable ideas, and compared the two repos' CI/release tooling.
The Nautobot plugin (v0.2.0) is past "basic" — it already has async NQE with
backoff, NQE diffs, snapshot-unchanged skip, redacted support bundle, query
contracts, contract-diff baseline, and a release-state gate. The transferable
value is in **governance / proof / write-path hardening** and, most of all, in
**GitOps automation** that forward-netbox built out over its 1.5.x → 1.6.0 line.

This plan has two parts:
- **Part A — Feature / hardening transfers** (product + governance)
- **Part B — GitOps workflows** (CI/release automation; the primary new ask)

---

## Part A — Feature / hardening transfers

Ordered by value-to-effort. NetBox-only mechanics (the Branching framework,
`netbox_branching` shards, bulk-ORM apply that bypasses change tracking) are
excluded — they fight the DiffSync + Nautobot change-logging model.

### A1. Signal / side-effect suppression during write  ·  High value · S–M
**forward-netbox:** `suppress_ingest_side_effect_signals()`
(`utilities/ingestion_merge.py:44`) is a context manager that disconnects
expensive ORM signal handlers (scope-recalc, change-notify, vc-master assign)
around the apply loop. Decision Log rule: suppress webhook/event-rule/scope
side effects, **never** the change record itself.
**Nautobot mapping:** wrap the DiffSync write phase in `write_executor.py` and
disconnect the hot Nautobot signals — dynamic-group membership recompute,
`m2m_changed` cache refresh, webhook enqueue — behind a config flag. Keep change
logging on.
**Why:** per-`save()` signal tax is the single biggest framework-safe write-path
cost on a large authorized validation dataset.

### A2. Live query source-proof gate  ·  High value · M
**forward-netbox:** `management/commands/forward_validation_org_query_audit.py`
+ `utilities/query_binding_resolution.py` publish the bundled `.nqe` set into a
dedicated Forward org repo folder, then prove byte-for-byte that the committed
query matches local source. Hardened in `f7bcd7e`/`0ad60f8` to resolve the
*latest concrete commit* (not `head`, which the index can satisfy without source
text) so the gate reports `proved` with `source_unavailable_count=0`. Has a
`--repair`/`--overwrite` self-heal mode and 409-retry handling.
**Nautobot mapping:** new management command + harness gate. We already have the
client repo access and contract scaffolding.
**Why:** `check_query_contracts.py` only proves the *local* `.nqe` parses to the
expected fields. Nothing today proves the `query_id` that actually runs in
production is the reviewed source. Our own perf plan flags this: the WF org
must publish `/forward_nautobot_validation/*` because runtime inline NQE is no
longer accepted.

### A3. Single aggregating release-readiness audit  ·  High value · M
**forward-netbox:** `forward_architecture_audit.py` emits one machine-readable
JSON: apply-engine matrix per model, model eligibility, fetch contracts,
documented blockers, classification gaps, validation-org sync status. CI-wired
gate (`22eab4f`), not a one-off. Companions: `forward_blocker_audit.py`,
`forward_warning_audit.py`, `forward_query_diff_coverage_audit.py`.
**Nautobot mapping:** aggregate our scattered `check_*.py` into one
`forward_architecture_audit` that fails if any supported model is unclassified,
any query lacks a contract, or a documented blocker regressed. Emits one
shippable/not-shippable artifact.
**Why:** silent coverage gaps bite when adding models — and the full-model
coverage plan is active.

### A4. Pre-flight sync health summary  ·  Med value · M
**forward-netbox:** `utilities/health.py:sync_health_summary(sync)` returns a
structured per-sync report — source reachability, per-model query
mode/reference/row-count/runtime, drift status, dependency preflight,
recommendations — each tagged pass/warn/fail.
**Nautobot mapping:** on-demand check backing a Job pre-run panel or detail-view
block. Pairs with `scripts/forward_dry_run.py`. Our support bundle is post-hoc;
this is pre-flight.

### A5. Collection-gap health signal  ·  Med value · M  ·  (new in 1.5.9/1.6.0)
**forward-netbox:** trends the "backfilled" (tagged but not freshly collected)
device count across runs, flags spikes in the health summary as a leading
indicator of a Forward *collection* problem (not a plugin bug). `f64347e`,
`41f644d`.
**Nautobot mapping:** surface devices present in a prior snapshot but absent from
the current collection, as a standing dashboard number with an "investigate
collection" call to action rather than a manual probe.

### A6. Sync observability — run-history panel  ·  Med value · M  ·  (new in 1.6.0)
**forward-netbox:** `f70639b` — per-sync run-history view: per-model
throughput/timing, change-volume trend, "what changed and why" (created/updated/
deleted by model + apply-engine decision + reason). Mostly surfacing existing
ledger data.
**Nautobot mapping:** Nautobot Jobs already store run history; add a per-model
timing/change-volume summary to the job result + a detail panel.

### A7. Scale-benchmark + parity-gate discipline  ·  Med value · S  ·  (methodology)
**forward-netbox:** every perf change ships behind a flag, defaults on only
after a stored before/after run shows equal-or-better runtime with identical
produced objects (`runtime_non_regression` gate, evidence under
`docs/03_Plans/evidence/`). The B4 revert (`b46c0bd`) proves why: update-batching
broke change visibility and was reverted with a Decision Log entry.
**Nautobot mapping:** adopt the rule for our perf plan; add a `forward_scale_benchmark`
helper that captures before/after wall-clock per change.

### Explicitly excluded
- Bulk-ORM apply engine / `bulk_create`/`bulk_update` — bypasses change tracking;
  fights DiffSync + Nautobot change logging.
- Branching framework, multi-branch planner, shard heartbeat — NetBox-specific,
  no Nautobot equivalent.
- Device analysis panel (reachability / blast-radius / CVE) — GA Forward
  capability, larger feature; park for later (large effort, separate plan).

---

## Part B — Local validation and release delivery

Superseded on 2026-08-06 by maintainer policy: validation and publishing are
local-only. The repository contains no GitHub-hosted automation.

### Current state

- `scripts/ci_local.py` runs sensitive-content, harness, release-state,
  query-contract, contract-diff, non-live tests, build, and wheel-content checks.
- `pre-commit run --all-files` provides the local lint and formatting gate.
- Disposable PostgreSQL/Redis stacks validate each supported Nautobot version
  locally before release.
- Live API tests remain opt-in and credentialed; no live identifiers or returned
  data are written to the repository.
- `scripts/release.py verify` invokes the complete local release gate and does
  not wait for any GitHub status check.
- `scripts/release.py` uploads locally built artifacts to GitHub Releases and
  PyPI after the local gate passes.

### Maintainer workflow

1. Run `pre-commit run --all-files`.
2. Run `python scripts/ci_local.py`.
3. Run the supported-version disposable stacks and authorized live smoke when
   the change affects runtime integration.
4. Merge the reviewed change, tag the validated commit, and publish the exact
   locally built artifacts with `scripts/release.py`.
5. Verify the GitHub release assets and public package index after delivery.

## Verification
- Unit: `python -m pytest -q -m "not integration"`
- Gates: every `scripts/check_*.py` + the new `scripts/release.py` helper tests
- Runtime: local disposable Nautobot stacks plus an authorized live smoke when applicable.
