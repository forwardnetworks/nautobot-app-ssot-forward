# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`nautobot-app-ssot-forward` (package `forward_nautobot`, distribution `nautobot-app-ssot-forward`)
is a Nautobot 3.1/3.2 app that syncs Forward Networks inventory, IPAM, and cloud data into Nautobot
through the `nautobot-ssot` framework. Read `ARCHITECTURE.md` before changing code; `AGENTS.md`
holds the repo's own agent rules and `docs/00_Project_Knowledge/validation-matrix.md` maps a change
type to the smallest gate that proves it.

Validation and publishing are deliberately local-only. There is no GitHub Actions or Dependabot
automation, and `scripts/check_harness.py` actively fails if `.github/dependabot.y*ml` appears.

## Commands

The system `python3` has neither Nautobot nor `forward-sdk`, and the plugin imports `forward_sdk`
at module load, so the suite fails collection there rather than skipping. Run everything in the
container stack below. There is deliberately no virtualenv in the repo. The pytest lines in this
block are the commands to run *inside* the container (via `docker compose ... exec -T nautobot`).

```bash
python3 -m pytest -q -m "not integration"          # unit suite (217 tests, ~seconds)
python3 -m pytest -q tests/test_planner.py         # one file
python3 -m pytest -q tests/test_planner.py -k scope_fingerprint   # one test
python3 -m pytest -q -m integration                # live Forward tests, needs FORWARD_LIVE_* env
ruff check . && ruff format .                      # lint/format (line-length 100, py311 target)
pre-commit run --all-files
```

Tests that need a real database (contrib sync, REST API, crypto) skip without a live Nautobot.
Run those in the container stack:

```bash
export NAUTOBOT_VERSION=3.2.9   # or 3.1.8; both are supported lines
docker compose -p fwdnautobot -f development/docker-compose.yml up -d --build
docker compose -p fwdnautobot -f development/docker-compose.yml \
  exec -T nautobot python -m pytest tests/ -q -p no:django
docker compose -p fwdnautobot -f development/docker-compose.yml down -v
```

Container-stack mechanics that are easy to get wrong:

- `ghcr.io` answers `denied` if `~/.docker/config.json` holds a stale ghcr credential, even though
  the Nautobot images are public. Point `DOCKER_CONFIG` at a directory containing `{}` for the
  build rather than editing your real config.
- Pass `-p no:django` so DB-backed tests hit the migrated dev database instead of a pytest-django
  test database with an access guard.
- The image entrypoint auto-migrates on startup. Do not run `nautobot-server migrate` by hand; it
  races. Wait for `showmigrations forward_nautobot` to show the latest migration applied.
- Live Forward runs: set `FORWARD_LIVE_BASE_URL`, `FORWARD_LIVE_USERNAME`, `FORWARD_LIVE_PASSWORD`,
  `FORWARD_LIVE_NETWORK_ID` and `FORWARD_LIVE_VERIFY_TLS=true`, then `pytest -m integration`. Most live
  tests skip until the bundled queries are published to that org (`forward_publish_queries`), and a
  few need a network with VRFs, IPv6 prefixes, modules or two snapshots, so a small lab skips them.
  Pass credentials by name (`docker compose exec -e VAR`), never as arguments, and keep network
  IDs and names out of tracked files.
- Write tests are not transaction-isolated against the shared database. Reset with `down -v` then
  `up` before an authoritative full run, or create-count assertions fail on a dirty database.
- The source tree is bind-mounted at `/source`, so edits are live without a rebuild.

Release gate and publication:

```bash
python3 scripts/ci_local.py            # full gate
python3 scripts/ci_local.py --fast     # skip build + wheel checks while iterating
python3 scripts/release.py X.Y.Z --summary "..."             # prepare + verify, no rollout
python3 scripts/release.py X.Y.Z --summary "..." --publish   # tag, GitHub Release, PyPI
```

`ci_local.py` chains: sensitive-content history scan, harness check, release-state check,
query-contract check, contract-diff report, the non-integration pytest suite under
`FORWARD_STRICT_NO_SKIPS=1`, build, wheel-contents, twine check, and a source-absent installed-wheel
probe against disposable stacks for both Nautobot versions. `FORWARD_STRICT_NO_SKIPS=1` means any
skipped non-integration test fails the gate, so a test that quietly skips outside the container is a
release blocker, not a neutral outcome.

Management commands (run through `nautobot-server`):

```bash
nautobot-server forward_fixture_seed        # deterministic demo profile + fixture
nautobot-server forward_demo_seed
nautobot-server forward_publish_queries --profile <name> --fail-on-gap [--overwrite|--audit-only]
nautobot-server forward_dry_run <fixture.json> --sample-size 5 --output /tmp/replay.json
nautobot-server forward_metrics             # Prometheus metrics
nautobot-server forward_health --profile <name> [--fail-on-warn]   # pre-flight: connectivity, network, snapshot, collection, queries
nautobot-server forward_architecture_audit  # registry vs packaged queries/contracts; exit 1 on a failing finding
nautobot-server shell < scripts/check_hand_made_objects.py   # hand-made objects with empty relations must not break a sync
nautobot-server shell < scripts/check_override_history.py    # applied delete overrides persist as rows
```

## Architecture

The single registered sync job is `ForwardInventoryDataSource`, a `nautobot_ssot.jobs.DataSource`
subclass in `forward_nautobot/integrations/forward/jobs.py`. SSoT owns run history, dashboard
discovery, and dry-run semantics; this repo owns everything from the Forward API down to the
Nautobot writes. Its class path is asserted by the release gate and must stay
`forward_nautobot.integrations.forward.jobs.ForwardInventoryDataSource`.

Flow through a run:

```
ForwardInventoryDataSource
  -> ForwardIngestionPlanner (planner.py)
     -> ForwardClient (client.py)          adapts forward-sdk; transport is the SDK's
     -> ForwardSourceAdapter (adapters.py) raw source rows
     -> NautobotTargetAdapter (adapters.py)
     -> ForwardWritePlanner (write_path.py)
  -> contrib_sync writes, only when SSoT dryrun is false
  -> support bundle pair (support.py), full plus redacted
  -> SSoT Sync.diff / Sync.summary
```

There is one write path: `contrib_sync.py`, which populates `NautobotModel` subclasses and lets
`nautobot-ssot` contrib CRUD (`source.sync_to(target)`) apply create/update/delete. The old
hand-rolled `write_executor.py`, the `use_contrib_sync` toggle and the registry's `write_handler`
field were removed; older `docs/03_Plans` still describe them as history. `contrib_sync` imports safely without Django and exposes
`CONTRIB_AVAILABLE`, which is how its tests decide to skip.

contrib delete-reconciles the whole target table, so deletes are gated twice. `delete_policy.py`
decides per model whether a delete is allowed (profile `delete_policy` is opt-in, default `ignore`;
zero-rows and fraction guards stop an under-collected slice wiping Nautobot). `managed.py` then
restricts deletes to objects carrying the `forward_managed` custom field, stamped on create/update.
The mark is a synced attribute, so the next sync adopts unmarked objects (the `managed.py`
docstring claims otherwise and is stale; `contrib_sync.py` and the check script are authoritative).
Unmarked objects are never deleted. `scripts/check_managed_ownership.py` proves this against a real
database (`nautobot-server shell < scripts/check_managed_ownership.py`, prints `OWNERSHIP: PASS`).

Key module boundaries beyond those already named:

- `registry.py` defines the model slices, their dependency order, identity fields, Nautobot scope,
  and the bundled `.nqe` filename each one reads. Adding a slice starts here.
- `cloud.py` owns cloud account scope, saved-query diff detection, and hydration for native Nautobot
  cloud CRUD.
- `query_publishing.py` owns query add/edit/commit plus exact committed-source verification.
- `contract_diff.py` and `queries/contracts.py` back the query-contract drift gates.
- Both `forward_nautobot/__init__.py` and `integrations/forward/__init__.py` use lazy `__getattr__`
  export maps, so Nautobot-dependent code imports without Django. In shell scripts, import the
  submodule directly rather than relying on the package attribute.

## Conventions that matter here

- **Keep contract fields unnormalized.** Rows coming out of NQE pass through Python raw. If a field
  shape needs to change, change the `.nqe` query, not the Python. `normalize.py` is a deliberate,
  narrow exception: it derives a canonical lookup key for Forward location strings while still
  writing the original first-seen name.
- **Saved queries are unparameterized and carry `@primaryKey`,** because the Forward `nqe-diffs`
  endpoint accepts no query parameters. Inline fallback strips only that annotation and is
  full-query-only, since diffs require a committed query ID. Diff failure is attributed to its slice
  and never silently replaced by a full query.
- **Filtered runs are create/update-only.** Device and cloud scope filters may never drive deletes or
  deactivation. A scope fingerprint is persisted with the snapshot so changing scope forces a new
  full query before diffs resume. The IPv4/IPv6 prefix slices carry no `scope_devices` field and
  therefore fail closed under a filtered run.
- **Cloud identity comes from immutable account and resource IDs,** never display names, and DiffSync
  loads only objects carrying the plugin's stable name suffix so unrelated cloud inventory stays
  outside reconciliation.
- **No customer identifiers anywhere in tracked content.** A pre-commit hook runs
  `scripts/check_sensitive_content.py` over both files and commit messages, and the release gate
  scans all history. That covers credentials, tenant names, network IDs, snapshot IDs, and
  screenshots.
- The version lives in two places that must move together, `pyproject.toml` and
  `ForwardNautobotConfig.version` in `forward_nautobot/__init__.py`. Let `scripts/release.py` do it.
- `scripts/check_harness.py` enforces required files, required headings in the plan and roadmap docs,
  and required literal phrases inside `README.md`, `ARCHITECTURE.md`, `SECURITY.md`, and the two
  Project Knowledge docs. Editing prose in those files can fail the gate. Read the constants at the
  top of that script before rewording.
- Track non-trivial work in `docs/03_Plans/active/` and durable repo knowledge in
  `docs/00_Project_Knowledge/`.
