# Forward Nautobot Performance & Quality Improvements

Date: 2026-06-17
Context: Switched back to async NQE on Forward 26.6. Live testing against the Wells Fargo
dataset surfaced an execution-payload bug and exposed several performance and quality
opportunities across the client, planner, and bundled NQE queries.

## Goal

Make the Forward → Nautobot sync as fast as possible while holding 100% production quality.
Adopt Forward 26.6 async execution features where they reduce request volume or runtime.

---

## P0 — Confirmed bug (live 400)

### `options.itemFormat` in execution POST is invalid

`request_nqe_execution` sends `payload["options"] = {"itemFormat": item_format}`. The live
26.6 API rejects this:

```
HTTP 400: Unrecognized field "options" (class NqeExecutionRequest), not marked as ignorable
(7 known properties: "commitId", "queryId", "columnFilters", "query", "parameters",
"sortKeys", "sortBy")
```

Result format is already negotiated correctly via the `Accept` header on the result GET
(`NQE_ASYNC_RESULT_ACCEPT`, prefers `application/x-ndjson`). The body field is dead and
breaks every live async execution.

- Evidence: `forward_nautobot/integrations/forward/client.py:725-726` (bad body),
  `client.py:689` (correct Accept header).
- Impact: every live async run fails / every live test skips. This is the root cause of the
  skipped Wells Fargo smoke runs.

**Action**

1. Remove the `options` key from the `request_nqe_execution` payload.
2. Remove the now-dead `item_format` thread end to end, or stop sending it in the body and
   keep only the result `Accept` negotiation. Callsites to clean:
   - `models.py:95` (`ForwardSyncSpec.item_format`)
   - `planner.py:34` (`ForwardIngestionRequest.item_format`) and `planner.py:352,371,420`
   - `runner.py:36`
   - `client.py:557,576,589,611,713,764`
3. Update tests that assert the bad payload:
   - `tests/test_client.py:553` and `tests/test_client.py:646`
     (assert `payload["options"]["itemFormat"]` — these pass only because mocks accept
     anything; the live API does not).
4. Re-run the live Wells Fargo async smoke to prove the full submit → poll → result path.

---

## P1 — Performance

### 1. Reuse a single httpx.Client

`_request` opens a new `httpx.Client(...)` per call (`client.py:99`). Every request pays a
fresh TCP + TLS handshake with no keep-alive. A `fetch_all` sync is
N slices × M pages × handshake.

**Action**: hold one long-lived `httpx.Client` for the `ForwardClient` lifetime (lazy-built,
honoring timeout/verify/transport/trust_env), reuse across requests, close on teardown.
Largest single perf win.

### 2. Parallelize independent slices

The planner runs slices strictly sequentially (`planner.py:301`): each slice does
submit → poll → page before the next starts. The dependency graph forces *some* ordering
(child slices inject parent keys as query parameters), but same-tier slices are independent —
e.g. `platforms` and `device_types` both depend only on `locations`.

**Action**: group slices by dependency tier (already have `depends_on` + topological order in
`registry.py`). Within a tier, submit all executions up front, then poll/collect. 26.6 async
executions are independent jobs, so this is safe.

### 3. Exponential poll backoff

`run_nqe_query_async` polls at a fixed 5s interval (`client.py:762`, `poll_interval_seconds=5.0`).
A query that completes at 1s still waits ~5s before the next status check.

**Action**: start small (e.g. 0.5s) and back off to a cap. Most NQE queries finish quickly;
this removes multi-second idle waits per slice.

### 4. Eliminate double resolution

`run_nqe_query` resolves snapshot + query spec (`client.py:562-565`), then
`request_nqe_execution` resolves both again (`client.py:718-721`). Caches blunt the cost, but
the redundant logic is avoidable.

**Action**: resolve once at the entry point and pass the resolved spec/snapshot down, or make
the inner method trust an already-resolved input.

---

## P2 — Forward 26.6 features worth adopting

### 5. Server-side sort (`sortKeys` / `sortBy`)

Now accepted by the execution API. Sorting by identity fields yields stable pagination and
lets us delete the `_page_signature` stall-detection heuristic entirely
(`client.py:485-545`).

### 6. Server-side filtering (`columnFilters`)

Now accepted. Push row filtering to Forward instead of pulling all rows and dropping them
client-side. Reduces transfer and parse cost.

### 7. `@primaryKey` on bundled NQE queries

None of the `.nqe` files declare `@primaryKey`. It enables device-parallel execution on the
Forward engine for faster query runtime. Every bundled query is `foreach device` shaped —
ideal candidates.

- Files: `forward_nautobot/integrations/forward/queries/*.nqe`

### 8. Stream NDJSON instead of buffering

`_parse_nqe_lines` buffers the whole `response.text` then `splitlines()` (`client.py:441`).
For large result sets, consume `response.iter_lines()` to cut peak memory.

---

## P3 — Quality

### 9. Narrow the planner's bare except

`planner.py:411` catches bare `Exception` and silently falls back to inline NQE. This masks
auth/network failures as "query path resolution failed."

**Action**: narrow to the expected resolution errors, and record which exception triggered
the fallback in the slice notes / support bundle.

---

## Suggested execution order

1. **P0** payload fix + dead `item_format` removal + test updates → re-run live WF smoke
   (fastest path to a green end-to-end run).
2. **P1.1** single httpx.Client (broad win, low risk).
3. **P1.3** poll backoff, **P1.4** dedupe resolution.
4. **P1.2** tier parallelism (largest structural win; sequence after the client is stable).
5. **P2** 26.6 features, starting with `@primaryKey` and server-side sort.
6. **P3** exception narrowing.

## Verification

- Unit: `python3 -m pytest tests/test_client.py tests/test_runner.py tests/test_planner.py`
- Live: load `.env` (Wells Fargo `FORWARD_WELLS_*`, mapped to `FORWARD_LIVE_*`), run
  `tests/test_live_ingestion.py -m integration`. The WF `org` repo does not publish the
  `/forward_nautobot_validation/*` paths, so live coverage relies on inline NQE or on
  pushing the bundled queries into a WF repo folder first.
