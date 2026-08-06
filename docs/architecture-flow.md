# Forward Field Integration — End-to-End Flow

This document shows how the plugin runs end to end across its three execution
modes, the connection types and direction between components, and the Forward
API calls made at each step. Intended for architecture review, onboarding, and
approval workflows.

GitHub renders the Mermaid diagrams below automatically.

---

## Execution modes at a glance

| Mode | When | NQE calls | What changes |
|---|---|---|---|
| **Skip** | `last_snapshot_id == current_snapshot_id` | 0 | Nothing — stamps `last_run_at` only |
| **Snapshot** | First run, or no saved query ID resolves | N slices × async execution | Full row set for each selected model slice |
| **Diff** | Saved query resolves AND baseline ≠ current | N slices × diff execution | Only rows changed between snapshots |

---

## Mode 1 — Skip (snapshot unchanged)

`last_snapshot_id` on the connection profile equals the current processed
snapshot. No NQE calls are made.

```mermaid
flowchart TB
    subgraph nautobot["Nautobot"]
        job["ForwardInventoryDataSource\nSSoT job triggered\n(UI or schedule)"]
        profile["Connection profile\nlast_snapshot_id = X"]
        db["Nautobot DB\n(unchanged)"]
    end

    subgraph fwd["Forward platform  (HTTPS · Basic Auth)"]
        snap["GET /snapshots/latestProcessed\nresolve current snapshot ID"]
    end

    job --> profile
    job -- "resolve snapshot" --> snap
    snap -- "returns X (same)" --> job
    job -- "stamp last_run_at\nno writes" --> db

    classDef neutral fill:#F1EFE8,stroke:#5F5E5A,color:#2C2C2A;
    classDef fwdnode fill:#E6F1FB,stroke:#185FA5,color:#042C53;
    classDef nbnode fill:#EDF6EC,stroke:#2E7D32,color:#1B5E20;

    class job,profile neutral;
    class snap fwdnode;
    class db nbnode;
```

---

## Mode 2 — Full snapshot sync

Runs when there is no prior baseline. Each bundled NQE first resolves to a saved
Forward repository query path/query ID. If it is not saved, the packaged source is
submitted inline through the same async API. Saved queries are diff-eligible; inline
fallback remains full-query-only.

```mermaid
flowchart TB
    subgraph nautobot["Nautobot"]
        job["ForwardInventoryDataSource\nSSoT job"]
        planner["ForwardIngestionPlanner\nbuild ingestion plan"]
        executor["ForwardNautobotWriteExecutor\napply plan — skipped on dry-run"]
        db["Nautobot DB\ncreate / update / mark-inactive"]
    end

    subgraph client["ForwardClient"]
        resolve_snap["GET /snapshots/latestProcessed"]
        prewarm["GET /nqe/repos/org/commits/head/queries\npre-warm query index cache"]
        submit["POST /nqe-executions\nsubmit async saved or inline query"]
        poll["GET /nqe-executions/{key}\npoll until COMPLETED\n(exponential backoff)"]
        result["GET /nqe-executions/{key}/result\nstream ndjson rows"]
    end

    job --> planner
    planner --> resolve_snap
    planner --> prewarm

    subgraph tier1["Tier 1 — parallel, maximum two submissions"]
        t1a["slice: locations"]
        t1b["slice: platforms"]
        t1c["slice: device_types"]
    end

    subgraph tier2["Tier 2 — parallel (devices)"]
        t2["slice: devices"]
    end

    prewarm --> tier1
    tier1 --> tier2
    t1a & t1b & t1c & t2 --> submit
    submit --> poll --> result

    result --> planner
    planner --> executor
    executor --> db

    classDef neutral fill:#F1EFE8,stroke:#5F5E5A,color:#2C2C2A;
    classDef fwdnode fill:#E6F1FB,stroke:#185FA5,color:#042C53;
    classDef nbnode fill:#EDF6EC,stroke:#2E7D32,color:#1B5E20;
    classDef tier fill:#F8F4FF,stroke:#7B1FA2,color:#4A148C;

    class job,planner,executor neutral;
    class resolve_snap,prewarm,submit,poll,result fwdnode;
    class db nbnode;
    class t1a,t1b,t1c,t2,tier1,tier2 tier;
```

---

## Mode 3 — Diff sync

Runs when the saved NQE query resolves to a query ID **and** a prior baseline
snapshot exists. Only rows that changed between snapshots are returned, reducing
transfer and parse cost for incremental runs.

```mermaid
flowchart TB
    subgraph nautobot["Nautobot"]
        job["ForwardInventoryDataSource\nSSoT job"]
        planner["ForwardIngestionPlanner"]
        executor["ForwardNautobotWriteExecutor"]
        db["Nautobot DB\napply delta"]
    end

    subgraph client["ForwardClient"]
        resolve_snap["GET /snapshots/latestProcessed\ncurrent = Y  (baseline = X)"]
        prewarm["GET /nqe/repos/org/commits/head/queries\nresolve saved query → queryId + commitId"]
        diff["POST /nqe-diffs/{X}/{Y}\nqueryId + commitId + page options\nreturns added / removed / unchanged rows"]
        fail["fail run with slice attribution"]
    end

    job --> planner
    planner --> resolve_snap
    planner --> prewarm
    prewarm -- "queryId resolved" --> diff
    diff -- "ForwardClientError" --> fail
    diff --> planner
    planner --> executor
    executor --> db

    classDef neutral fill:#F1EFE8,stroke:#5F5E5A,color:#2C2C2A;
    classDef fwdnode fill:#E6F1FB,stroke:#185FA5,color:#042C53;
    classDef nbnode fill:#EDF6EC,stroke:#2E7D32,color:#1B5E20;
    classDef warn fill:#FAEEDA,stroke:#854F0B,color:#412402;

    class job,planner,executor neutral;
    class resolve_snap,prewarm,diff fwdnode;
    class db nbnode;
    class fail warn;
```

---

## NQE query resolution

Each model slice tries to resolve its bundled `.nqe` file to a saved query in
the Forward NQE repository. The query mode recorded in the run output reflects
which path was taken.

```mermaid
flowchart LR
    start(["_fetch_slice\nfor one model"])

    try_resolve["resolve_query_spec\nlook up query path in repo index"]
    inline["bundled_nqe_inline_async\nstrip @primaryKey and submit\npackaged source asynchronously"]
    saved_snap["bundled_nqe_query_id_async\nfull snapshot via async queryId"]
    saved_diff["bundled_nqe_query_id_diff\ndiff via saved queryId\n(fastest incremental)"]
    fail["fail run with slice attribution\nno silent full-query fallback"]

    start --> try_resolve
    try_resolve -- "ForwardClientError\n(path not in repo)" --> inline
    try_resolve -- "resolved\nbaseline == current\nor no baseline" --> saved_snap
    try_resolve -- "resolved\nbaseline != current" --> saved_diff
    saved_diff -- "ForwardClientError" --> fail

    classDef neutral fill:#F1EFE8,stroke:#5F5E5A,color:#2C2C2A;
    classDef fwdnode fill:#E6F1FB,stroke:#185FA5,color:#042C53;
    classDef warn fill:#FAEEDA,stroke:#854F0B,color:#412402;

    class start,try_resolve neutral;
    class fail warn;
    class saved_snap,saved_diff,inline fwdnode;
```

---

## Tier parallelism and dependency order

Slices within a tier are dispatched concurrently, with at most two outstanding
async submissions. Tiers are gated so prerequisite rows exist before dependent
Nautobot objects are planned. Query execution itself is unparameterized to preserve
saved-query primary keys and NQE-diff eligibility.

```mermaid
flowchart LR
    subgraph t0["Tier 1  (parallel, maximum two at once)"]
        locations["locations"]
        platforms["platforms"]
        device_types["device_types"]
    end

    subgraph t1["Tier 2  (parallel)"]
        devices["devices\n← location + platform + type rows"]
        vlans["vlans\n← locations"]
    end

    subgraph t2["Tier 3  (parallel, disabled by default)"]
        interfaces["interfaces\n← devices"]
        vrfs["vrfs\n← devices"]
        inv["inventory_items\n← devices"]
        mod["modules\n← devices"]
    end

    subgraph t3["Tier 4  (parallel, disabled by default)"]
        ip4["ipv4_prefixes\n← VRFs"]
        ip6["ipv6_prefixes\n← VRFs"]
        ipa["ip_addresses\n← devices + interfaces + VRFs"]
    end

    t0 --> t1 --> t2 --> t3

    classDef neutral fill:#F1EFE8,stroke:#5F5E5A,color:#2C2C2A;
    class locations,platforms,device_types,devices,interfaces,vlans,vrfs,ip4,ip6,ipa,inv,mod neutral;
```

---

## Forward API calls summary

| Call | When | Purpose |
|---|---|---|
| `GET /networks/{id}/snapshots/latestProcessed` | Every run | Resolve current snapshot ID |
| `GET /nqe/repos/org/commits/head/queries` | Every run (once, cached) | Pre-warm query index; resolve `.nqe` paths to query IDs |
| `POST /networks/{id}/nqe-executions` | Snapshot mode, per slice | Submit an async saved query or packaged inline query |
| `GET /networks/{id}/nqe-executions/{key}` | After submit | Poll execution status |
| `GET /networks/{id}/nqe-executions/{key}/result` | Status = COMPLETED | Stream ndjson result rows |
| `POST /nqe-diffs/{before}/{after}` | Diff mode, per saved slice | Execute a primary-keyed saved query across two snapshots |

No NQE calls are made in skip mode. Diff mode uses the dedicated diff endpoint;
its request contains query identity, commit identity when available, and page options,
but no query parameters.

---

## Permissions required

### Plugin → Forward (HTTPS · Basic Auth)

| API call | Required Forward permission |
|---|---|
| `GET /snapshots/latestProcessed` | read snapshots |
| `GET /nqe/repos/org/commits/head/queries` | read NQE repository |
| `POST /nqe-executions` | execute NQE |
| `GET /nqe-executions/{key}` | read NQE executions |
| `GET /nqe-executions/{key}/result` | read NQE results |
| `POST /nqe-diffs/{before}/{after}` | execute NQE diffs |

### Plugin → Nautobot DB (Django ORM, same process)

| Operation | Models touched |
|---|---|
| Read existing objects for diff | `Location`, `Device`, `DeviceType`, `Platform`, `Interface`, `VLAN`, `VRF`, `Prefix`, `IPAddress` |
| Create / update / mark-inactive | Same set — scoped to selected model slices |

### Configuration prerequisites in Nautobot

| Prerequisite | Required for |
|---|---|
| `LocationType` (e.g. `Site`) | Writing locations |
| `Status` with `Location` content type (e.g. `Active`) | Writing locations |
| `Role` with `Device` content type (e.g. `Network Device`) | Writing devices |
| `Status` with `Device` content type (e.g. `Active`) | Writing devices |

All four must exist before the first sync. The plugin does not create them
automatically.

---

## Key operational properties

- **Dry-run safe** — `ForwardNautobotWriteExecutor` is skipped entirely when the
  SSoT job runs with `dryrun=True`. The plan is computed and reported; no DB
  writes occur.
- **Incremental by default** — the planner records `last_snapshot_id` on the
  connection profile after every successful run. Subsequent runs use diff mode
  when the query is resolvable, or skip entirely when the snapshot is unchanged.
- **Exact-set device scope** — a full current-device membership query selects the
  configured manufacturers, functional classes, and models. The planner then filters
  both full and diff rows using direct `device` or raw `scope_devices` attribution.
- **Diff-compatible requests** — saved bundle queries declare their own primary keys.
  The planner omits query parameters and `sortKeys`, both of which were rejected by
  the verified saved-query/diff path for some multi-key contracts.
- **Filtered reconciliation safety** — filtered runs suppress deletion and deactivation.
  Prefix slices fail closed under filters because their compact route-table queries do
  not expose per-device contributors; unfiltered prefix sync remains supported.
- **Support bundle** — every run produces a sanitized support bundle alongside
  the SSoT sync record, capturing row samples, query modes, diff summaries, and
  redacted connection metadata for offline diagnostics.
