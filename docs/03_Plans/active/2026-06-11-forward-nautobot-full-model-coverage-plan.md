# Forward Nautobot Full Model Coverage Plan

## Goal

Expand the Forward Nautobot plugin from a curated first slice set into a registry-driven
integration that can cover the Nautobot model surface we intentionally choose to support.

The expansion stays contract-first:

- NQE remains the source of truth for row shape and normalization.
- Python preserves raw contract fields instead of reshaping them post hoc.
- A model is only supported when it has a stable identity, a write plan, and a deterministic
  lookup path.

## What "Full Coverage" Means

This does not mean "every Nautobot model by default."

It means the repo can separate models into clear tiers:

| Tier | Meaning | Runtime behavior |
| --- | --- | --- |
| Supported and writable | Stable identity, explicit query contract, lookup path, write handler, and tests | Listed in the registry and executed by the sync path |
| Supported and read-only | Stable identity and contract, but no safe write semantics yet | Visible in UI and jobs, but excluded from writes |
| Deferred | No stable contract yet, unsafe dependency behavior, or unclear business value | Kept out of the runtime path until the contract is explicit |

## Core Direction

Move the plugin from this shape:

```text
hard-coded model list
  -> hard-coded lookup branches
  -> hard-coded write branches
  -> per-model test additions
```

to this shape:

```text
model registry
  -> query contracts
  -> lookup dispatch
  -> write dispatch
  -> table-driven tests
```

That lets the model set grow without turning the plugin into a maze of one-off conditionals.

## Expansion Method

To support more Nautobot models, add them in dependency-safe batches:

1. Pick a model family with a stable raw contract.
2. Add or update its NQE query so the row shape is already final when Python sees it.
3. Register the model with explicit identity, lookup, write, and dependency metadata.
4. Wire the lookup/write dispatch through the registry instead of another hard-coded branch.
5. Add fixture-backed tests that prove the contract and the target-state mapping.
6. Expose the model through the UI only after the contract and tests are in place.

The registry should describe both current support and future candidates, but only the supported
entries should be wired into the runtime path.

## Implementation Workstreams

### 1. Registry as the source of truth

Promote the model registry into a real catalog with explicit metadata per model:

- `slug`
- `forward_query_file`
- `nautobot_scope`
- `identity_fields`
- `write_mode`
- `missing_row_policy`
- `enabled_by_default`
- `dependency_group`
- `depends_on`
- `lookup_strategy`
- `write_handler`

### 2. Registry-driven lookup

Replace `lookup_object()` branching with dispatch that reads from the registry.

That keeps lookup logic aligned with the supported model list and avoids a growing chain of ad hoc
special cases.

### 3. Registry-driven write execution

Move per-model Nautobot write behavior into handler functions selected by model metadata.

This is required for models with different keying rules, missing-row policies, or dependency
handling.

### 4. Contract-complete NQE for each supported model

For every supported model, add or update an NQE contract that:

- emits stable identity fields
- uses the right field names directly
- avoids Python-side normalization
- encodes optional values in a way that still preserves identity and adapter compatibility

If a model cannot produce a stable raw identity, it should remain unsupported until the query
contract is fixed.

### 5. Dependency-aware write ordering

Some Nautobot models depend on others being present first.

The registry should declare those dependencies so the write path can order work correctly for
objects like:

- locations before devices
- device types before devices
- devices before interfaces, inventory items, and modules
- VRFs and VLANs before IPAM-dependent rows where applicable

### 6. UI and job surface generation

The UI should list supported models from the registry instead of duplicating the model list in
templates.

The job config and summary surface should likewise render supported slices from the registry so the
plugin remains clear as model coverage expands.

### 7. Table-driven tests

Add tests that assert every registry entry has:

- a query file
- a Nautobot scope
- usable identity fields
- a lookup path
- a write path
- a contract version

Add fixtures that prove the new models load and write without changing the raw row contract in
Python.

### 8. Query-load guardrails

As the model set expands, keep the Forward load bounded:

- prefer query IDs and `nqe-diffs` when a saved query is available
- allow inline query text for ad hoc runs
- keep query filters parameterized where possible
- avoid repeated lookups and avoid turning a single model batch into many small API calls

## Recommended Rollout Order

1. Convert the registry into the central model catalog.
2. Make lookup and write execution registry-driven.
3. Add one new model family end to end as a proof point.
4. Expand the registry in small batches.
5. Keep each batch accompanied by a contract test and a fixture-backed smoke test.

## Guardrails

- Do not add models just to claim breadth.
- Do not normalize payloads in Python when the query should be doing that work.
- Do not make a model writable before the lookup and dependency rules are explicit.
- Do not let UI labels diverge from the registry.

## Exit Criteria

The expansion work is ready for the next tranche when:

- supported models are declared in one registry
- lookup dispatch is data-driven
- write execution is data-driven
- each supported model has a matching NQE contract
- fixture tests cover the expanded model set
- the UI reflects the supported model catalog without manual duplication
