# Forward-NetBox Learnings — Backlog & Top-4 Implementation

Date: 2026-06-28
Branch: `redesign/diffsync-crud`
Status: in progress

## Origin

A multi-agent survey mined the sibling **forward-netbox** plugin (standalone
NetBox, v1.5.0, ~40 completed enhancement plans) for usability / observability /
coverage / governance work applicable to **this** plugin. An adversarial critique
pass then corrected the synthesis — several proposed items were oversold or built
on false premises (a model that does not exist in Nautobot 3.1; gates that already
exist; NetBox-only plumbing). What follows is the **corrected** backlog.

Guiding rule: we are built on `nautobot-ssot`, so run history, the diff/dry-run
view, per-object `SyncLogEntry`, and the Job-result UI are **free**. A real
learning is something the framework does **not** provide. Anything forward-netbox
built to reimplement SSoT in NetBox is explicitly *not* ported.

## Top-4 — implement now (framework-absent, data we already hold, small effort)

### 1. Failure-surface enrichment + support-bundle download  (S)
On a hard failure we record only `error: <type>: <msg>` and throw away **which
slice** and **which Forward NQE query** broke (`jobs.py` `_run_ingestion_plan`
except branch). nautobot-ssot's JobResult has the raw traceback but not the
Forward-domain attribution — only we hold that.
- Capture failing-slice + query reference onto the failure record / profile.
- Add a one-click **support-bundle download** (no route / `FileResponse` exists
  today; `views.py` renders `last_support_bundle` as a bare string).
- De-duplicate "Last failure" vs "Run outcome" on the Status page.

### 2. Per-slice `query_runtime_ms` + `commit_id`  (S/M)
Row-count and query-reference already flow into `diff_detail`; the genuinely
missing bits are **per-fetch timing** (we only have `time.monotonic` for
rate-limiting, never elapsed) and the already-resolved **`commit_id`** (resolved
in `_fetch_slice` but never recorded). Source-side fetch is the dominant
cost/failure mode for a Forward integration and ssot's whole-adapter
`source_load_time` blurs it across all slices.
- Time each `_fetch_slice`; surface `query_runtime_ms` + `commit_id` per slice in
  `diff_detail_slices` (→ diagnostics page + support bundle).

### 3. Forward API/NQE usage counters in the support bundle  (M, trimmed)
The client retries / throttles / sees 429s / runs NQE queries and counts **none**
of it — silent slowness. nautobot-ssot tracks DiffSync object CRUD, never the
Forward REST transport.
- Add counters to `ForwardClient`: `http_attempts`, `http_transient`, `http_429`,
  `http_retries`, `nqe_query_calls`, `throttle_sleep_seconds`.
- Emit an `api_usage` section in the support bundle / diagnostics dict.
- **Dropped from the original proposal:** the observed-vs-budget pass/warn/fail
  SLO layer (gold-plating) and a Status-page health card (needs a model +
  migration) — those are a separate follow-on, not part of the top-4.

### 4. `Interface.mac_address` attribute  (S — corrects a wrong proposal)
The survey proposed a `dcim.MACAddress` slice — **wrong**: no standalone
`MACAddress` model exists in Nautobot 3.1 (that is a NetBox 4.2 construct). MAC is
a field on `Interface`. Correct fix: emit `mac_address` from `forward_interfaces.nqe`
(`interface.ethernet.macAddress`) and add it to the existing Interface contrib
slice.

## Medium — real, scoped (not in this pass)

- **Delete-governance audit (P1, not P0).** Legacy `write_executor` already
  refuses deletes past `reconcile_max_delete_fraction`; the contrib path can't
  delete at all today (`allow_delete=False`). Real residual = a *persisted
  override record* (who/why/when), a *zero-rows gate*, and *fraction-gate parity*
  when `delete_policy → allow_delete` is eventually wired on the contrib path.
- **`dcim.Cable` slice.** Genuine coverage gap (topology, absent everywhere).
  Needs **custom CRUD** — terminations are a `GenericRelation`, LAG endpoints
  aren't cableable, already-cabled conflicts. forward-netbox `sync_cable.py` is a
  blueprint.
- **Changed-field rollup** ("description ×380, mtu ×30"). Only the snapshot-diff
  path retains before/after; dominant paths store after-only — needs a planner
  change to retain `before`, so not pure aggregation.
- **Repeat-apply idempotence CI test** (prefix/ip families) — assert second run
  is a no-op / zero ObjectChange.
- **Offline bundle grader** — thresholds → pass/warn/fail over our bundle
  metrics; skip forward-netbox's branching/bulk-ORM metrics.

## Defer / low (P3)

Source-proof gate → reframe to **commit-pin drift** (byte-equality false-alarms
because we deliberately mutate the `.nqe` before exec); FHRP-VIP / VirtualChassis /
feature-tags (low value); headless smoke script (80% already exists in
`forward_drift_export` + live smoke tests); oversized-param partition (protects a
scoped-fetch feature we don't have).

## Explicitly DON'T build

forward-netbox's `ForwardExecutionRun/Step` ledger, watch-sync, job-liveness
probes, resumable-shard/branching recovery — all exist only because NetBox has no
SSoT framework. `Sync`/`SyncLogEntry` + the Celery job lifecycle give us run
history, restart-by-rerun, logs, and live status for free. Also non-problems:
runtime param-contract enforcement, signal suppression (incoherent for our path),
`change_request_id` (just a `StringVar`), contract-diff gate (already wired in CI).

## Acceptance

- Top-4 implemented behind the existing code paths, no new models/migrations.
- Full test suite green; new unit tests for counters + failure attribution + the
  interface MAC attribute.
- `ruff check` / `ruff format` clean.
