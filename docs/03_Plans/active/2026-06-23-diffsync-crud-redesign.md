# DiffSync/NautobotModel CRUD Redesign

Date: 2026-06-23
Branch: `redesign/diffsync-crud`
Status: in progress (post-0.3.0)

## Goal

Replace the hand-rolled diff + write engines with the standard nautobot-ssot
`contrib` path, so writes flow through the framework's CRUD and a single diff.
Keep the Forward read layer (client/NQE) and the source-row production intact.

## Why (from the 2026-06-19 architecture review)

The plugin wears the SSoT/DiffSync costume but bypasses the engine: DiffSync
models are inert (no CRUD), `.sync()` is never called, and three parallel diff
implementations exist (real diffsync, the fallback `sync_to` shim, and the
dict-equality `ForwardWritePlanner`), applied by a separate ~1,100-line
`ForwardNautobotWriteExecutor`. They can and do disagree, and the SSoT
"View Diff"/per-record logging features are reinvented or degraded.

## Target architecture

- **Source adapter** — keep producing raw Forward rows per slice (NQE layer
  unchanged), but populate `NautobotModel` subclasses instead of plain
  `DiffSyncModel`.
- **Target adapter** — `nautobot_ssot.contrib.NautobotAdapter`: declares the
  models + `top_level`, auto-loads current Nautobot state from the ORM.
- **Sync** — the SSoT `DataSource` calls `calculate_diff()` + `execute_sync()`;
  CRUD comes from `NautobotModel.create/update/delete`. Delete `ForwardWritePlanner`,
  `_build_delta_plan`, and `ForwardNautobotWriteExecutor`.

## Hard constraints discovered in contrib 4.4.0 (`contrib/model.py`)

1. **FKs are resolved by lookup, not created.** `_lookup_and_set_foreign_keys`
   does `adapter.get_from_orm_cache(params, related_model)` and raises
   `DoesNotExist` if absent. Consequences:
   - Every FK target must already exist at write time: either synced as its own
     model earlier in `top_level` order, or ensured to exist before sync.
   - FK attributes are expressed as `field__lookupfield` on the model
     (e.g. `location__name`, `status__name`, `device_type__model`).
2. **No per-row prerequisite creation.** Role / Status / LocationType defaults
   that the old executor auto-created must be ensured-to-exist once at job start
   (a `_ensure_prerequisites()` step), with the right content-types attached.
3. **Identity == diffsync identifiers.** Location dedup can no longer live in the
   writer. It must move to **source-row normalization**: collapse formatting
   variants to one canonical row before they become diffsync objects, so the
   source presents one Location per physical site. Reuse `normalize_location_key`.
4. **Transactions / delete safety.** SSoT wraps `execute_sync` in its own
   transaction and honors dryrun. The reconcile max-delete-fraction safeguard has
   no direct contrib equivalent — re-add it as a pre-sync check on the computed
   diff (count deletes per model vs current table) before `execute_sync`.

## Model inventory + FK map (what each NautobotModel needs)

| slug | _model | identifiers | key attrs (FK as `x__y`) | FK prereqs |
|---|---|---|---|---|
| manufacturers* | dcim.Manufacturer | (name,) | — | — |
| locations | dcim.Location | (name,) | location_type__name, status__name | LocationType, Status |
| platforms | dcim.Platform | (name,) | manufacturer__name | Manufacturer |
| device_types | dcim.DeviceType | (manufacturer__name, model) | — | Manufacturer |
| devices | dcim.Device | (name,) | location__name, role__name, status__name, device_type__model, platform__name | Location, Role, Status, DeviceType, Platform |
| interfaces | dcim.Interface | (device__name, name) | type, enabled, ... | Device |
| vlans | ipam.VLAN | (location__name, vid) | name, status__name | Location, Status |
| vrfs | ipam.VRF | (name,) | — | — |
| ipv4/ipv6_prefixes | ipam.Prefix | (prefix, vrf__name) | status__name | VRF, Status |
| ip_addresses | ipam.IPAddress | (...) | status__name | (parent chain) |
| inventory_items | dcim.InventoryItem | (device__name, name) | manufacturer__name | Device, Manufacturer |
| modules | dcim.Module | (device__name, module_bay) | module_type, status__name | Device |

\* manufacturers is likely a NEW synced model (devices/device_types/platforms all
reference it; contrib won't auto-create it).

## Status (2026-06-23)

Implemented + live-validated on real PostgreSQL via contrib CRUD, all idempotent
and delete-safe by default:
- **Network (complete):** locations, manufacturers, platforms, device_types,
  devices, interfaces, vrfs, vlans, prefixes (v4/v6), ip_addresses,
  inventory_items, module_types, module_bays, modules.
- **Cloud:** cloud_account, cloud_network (VPC+subnet), cloud_service, with the
  three cloud NQEs authored and executing against the live tenant.
- **Cutover wiring + LIVE proof:** `run_contrib_full_sync` orchestrates the whole
  import; the SSoT Job routes to it when
  `PLUGINS_CONFIG["forward_nautobot"]["use_contrib_sync"]` is true (legacy executor
  remains the default). Proven end to end against the live WF tenant: 100
  locations + 100 devices fetched via NQE -> 218 Nautobot objects created through
  contrib CRUD; re-sync 218 no-change; cloud NQEs executed (empty on a network
  tenant). The full chain — Forward NQE fetch -> unified contrib -> Nautobot —
  works.

Remaining residuals:
- A **managed-object filter** so `allow_delete=True` is safe (delete is off by
  default today); then delete the legacy write engine once the flag is promoted.
- A few NQE slices (interfaces, inventory_items) **HTTP 500 server-side at WF
  scale** on the inline path — a pre-existing Forward heavy-query issue that
  affects the legacy engine identically; orthogonal to the redesign. Needs a
  lighter/paged NQE or a published saved query.

## Phases

1. **PoC — locations end to end (this branch).** Add `_ensure_prerequisites`,
   a `ForwardContribLocation(NautobotModel)`, a contrib source+target adapter,
   and a parallel `sync_data_contrib` behind a flag. Prove create/update/no-change
   + dedup-in-source + View Diff on the box. De-risks FK lookup, prereqs, dedup.
2. **Core models** — manufacturers, platforms, device_types, devices. Prove the
   FK chain (devices resolve all five FKs by lookup).
3. **IPAM + assets** — vlans, vrfs, prefixes, ip_addresses, inventory_items, modules.
4. **Delete safety + delta** — port the max-delete-fraction guard as a pre-sync
   diff check; decide delta-snapshot handling (NQE diff still feeds source rows;
   contrib computes create/update/delete against the loaded target).
5. **Cutover** — flip the flag default, delete `write_path.py`,
   `write_executor.py`, `_build_delta_plan`, the fallback `Adapter.sync_to`
   shim, and the dict-equality planner diff. Update tests.

## CRITICAL finding — delete scoping (gates cutover)

`source.sync_to(target)` delete-reconciles the **entire** target table: any object
the source does not contain is DELETED. Validated on the box — a device-only sync
tried to delete cloud-provider Manufacturers (ProtectedError). At real scale this
would wipe every Nautobot object the plugin does not manage (manually-added
devices, other integrations' data, cloud providers).

Phase 4 MUST add delete scoping before the contrib path can drive a real Job:
- Filter each target adapter's queryset to only Forward-managed objects (e.g. by a
  tag/custom-field the plugin stamps on create, or by the set of identities the
  source produced this run), OR
- Run a diff and apply only create/update (+ scoped deletes), reusing the
  0.3.0 reconcile max-delete-fraction guard as a backstop.
Until then the contrib runners are create/update-safe only when the target starts
empty or the source is the full inventory.

**RESOLVED (default-safe):** a `_ForwardContribDeleteMixin` on every contrib model
skips the ORM delete unless the target adapter sets `allow_delete=True` (runners
default it False). Proven on the box: a Cisco-only scoped sync left an unmanaged
"Orphan Networks Inc" Manufacturer intact (no ProtectedError); the diff still
*counts* would-deletes but none are applied. Remaining for full delete support:
a managed-object filter (tag/custom-field stamped on create) so `allow_delete=True`
removes only Forward-owned objects, plus the max-delete-fraction backstop.

## Test strategy

- Unit: each NautobotModel's identity/attrs map; source normalization/dedup;
  the pre-sync delete-fraction guard. Keep the DB-less pattern (contrib adapter
  load tolerates no-DB in unit env / is skipped via the table guard).
- Live WF smoke on the box at each phase (real PostgreSQL): create, re-run
  (no-change), dedup count, View Diff render, dryrun-vs-apply parity.

## Rollback

Everything is on `redesign/diffsync-crud` behind a flag until Phase 5. `main`
stays shippable for the demo; if the redesign isn't ready, the demo ships the
0.3.0 hand-rolled path unchanged.
