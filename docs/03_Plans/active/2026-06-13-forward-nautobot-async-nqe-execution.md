# Forward Nautobot Async NQE Execution Tranche

## Goal

Add a bounded async NQE execution path for live testing and future query-id-backed runs without baking host-specific
details into the repo. The supported query execution flow now assumes Forward 26.6 or newer.

## Scope

- route all supported NQE executions through async submit, status polling, and result paging
- exercise the async path with a live smoke that resolves repository query paths to query IDs
- keep live request volume bounded and parameterized
- keep host, credential, network, and snapshot details env-driven only

## Checklist

| Item | Evidence | Status |
| --- | --- | --- |
| Async execution transport exists in the Forward client | `forward_nautobot/integrations/forward/client.py` | complete |
| Async execution flow has unit coverage | `tests/test_client.py` | complete |
| Live async smoke uses query-path-backed query IDs | `tests/test_live_ingestion.py` | complete |
| Repo contains no hardcoded demo host or credentials | tracked files | complete |

## Next Step

Verify the new async execution helpers and live smoke with tests, then keep the planner on the async path going
forward. The async switchover is complete for supported query execution surfaces; diff execution remains a separate
transport.
