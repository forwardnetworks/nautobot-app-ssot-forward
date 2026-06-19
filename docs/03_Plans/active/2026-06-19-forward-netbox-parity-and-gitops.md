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
cost on the Wells Fargo–scale dataset.

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
doesn't publish `/forward_nautobot_validation/*`, so we run inline NQE
unverified.

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

## Part B — GitOps workflows  (primary new ask)

### Current state — gap analysis

| Capability | forward-netbox | nautobot plugin (us) |
|---|---|---|
| CI on push/PR | yes | yes |
| Version matrix | NetBox v4.5.9 + v4.6.2 | **none** (single Py 3.11) |
| pre-commit | `pre-commit run --all-files` | **none** |
| Lint/format config | ruff + flake8 + pre-commit hooks | **none** |
| Harness gate | yes | yes |
| Live integration in CI | **docker-compose NetBox + PG + Redis + migrate + django checks** | **none** (we tested by hand on 192.168.1.167) |
| Docs build gate | `mkdocs build --strict` | **none** |
| Release automation | `scripts/release.py` + `invoke release` | **none** (manual; hit a stale-tag bug this session) |
| Release publish | GH release + PyPI | GH release only |
| Local CI mirror | yes (release.py verify stage) | **none** |

### B1. Release automation script  ·  Highest leverage · S
**Model:** `forward-netbox/scripts/release.py` (`06e357e`) encodes the whole flow
with CI gotchas baked in: `git add -A` *before* the local mirror (so the
sensitive-content guard, which is tracked-files-only, sees new files); run
pre-commit twice for convergence; keep the plan file in the same push (harness
gate). Stages: `prepare` (bump version + doc tables + scaffold plan),
`verify` (full local CI mirror), `publish` (branch → push → wait for CI →
fast-forward main → tag → GH release → PyPI → sync local main), gated behind
`--publish`.
**For us:** `scripts/release.py` that:
1. `prepare` — bump `pyproject.toml` **and** `forward_nautobot/__init__.py`
   version in lockstep, scaffold the release plan file.
2. `verify` — run the full gate set locally (all `check_*.py`, pytest non-int,
   build, wheel-contents).
3. `publish` (`--publish` only) — branch, push, wait for CI, fast-forward main,
   **move/create the tag on the right commit**, GH release with artifacts,
   optional PyPI.
**Why:** we manually cut v0.2.0 this session and the tag went stale two commits
later — exactly the class of error this removes. Pure-logic helpers
(`bump_version_text`, etc.) are unit-testable.

### B2. pre-commit config + lint/format  ·  S
Add `.pre-commit-config.yaml` (ruff, ruff-format / black, end-of-file, trailing
whitespace, yaml/json check) and wire `pre-commit run --all-files` into CI.
We currently have no lint gate at all.

### B3. Nautobot version matrix in CI  ·  S–M
Run the test job across a Nautobot version matrix (e.g. 3.1.x current + the next
minor) like forward-netbox's NetBox matrix, so we catch ORM/API drift before a
user does. `Role`-vs-`DeviceRole` (which bit us on 192.168.1.167) is exactly the
breakage a matrix surfaces.

### B4. Live Nautobot integration in CI  ·  M  ·  highest correctness value
Spin up Postgres + Redis + Nautobot in docker-compose in CI, run migrations,
django system checks, and our integration tests (the locations-write,
skip-if-same-snapshot, and diff-path checks we ran by hand on the Linux box).
Forward-netbox does exactly this for NetBox. Gate live-API tests behind presence
of `FORWARD_LIVE_*` secrets so forks/PRs still pass without creds.

### B5. Local CI mirror  ·  S
`invoke ci` (or `scripts/ci_local.py`) that runs the identical gate set CI runs,
so a release is verified before push. Folded into `release.py verify`.

### B6. Publish to PyPI on release  ·  S
Extend `release.yml` to `twine upload` (trusted publishing / OIDC preferred) in
addition to GH release assets. Currently we attach wheels to the GH release only.

### B7. Dependabot / action pinning  ·  S
Add `.github/dependabot.yml` for GitHub Actions + pip, and pin actions to SHAs.
Our workflows mix `@v5`/`@v6`/`@v7.0.1` tags.

---

## Suggested execution order

1. **B1 release automation** (immediate toil + stale-tag fix; we just felt the pain).
2. **B2 pre-commit + B5 local CI mirror** (foundation the rest leans on).
3. **B3 version matrix + B7 dependabot** (cheap drift protection).
4. **B4 live integration in CI** (highest correctness value; larger).
5. **A1 signal suppression** (biggest framework-safe write speedup).
6. **A2 source-proof gate** (closes the production-trust hole our perf plan flags).
7. **A3 aggregating audit + A7 parity discipline** (governance).
8. **A4–A6** (observability surfaces) as a follow-on tranche.
9. **B6 PyPI publish** once a PyPI project exists.

## Verification
- Unit: `python -m pytest -q -m "not integration"`
- Gates: every `scripts/check_*.py` + the new `scripts/release.py` helper tests
- Live: docker-compose Nautobot in CI (B4); manual WF smoke on 192.168.1.167 as
  the fallback until B4 lands.
