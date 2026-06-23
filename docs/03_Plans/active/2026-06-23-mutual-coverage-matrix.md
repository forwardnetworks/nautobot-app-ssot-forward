# Forward ↔ Nautobot Mutual Coverage Matrix

Date: 2026-06-23
Branch: `redesign/diffsync-crud`

Goal: import every network + cloud object Forward (via NQE) and Nautobot mutually
support. This matrix is the evaluation; implementation lands as contrib
`NautobotModel` slices (see 2026-06-23-diffsync-crud-redesign.md).

## Forward NQE exposes (all via inline `POST /api/nqe`)

- **Network:** devices, platform (vendor/model/os/components), system, interfaces
  (+subinterfaces, IPv4/IPv6 addresses, ARP, CDP/LLDP), VLANs, VRFs/network
  instances, FIB routes/prefixes, BGP/OSPF, ACL/NAT, security zones/policy,
  hosts, HA/MLAG, CVEs, hardware components (modules/inventory).
- **Cloud (`network.cloudAccounts.*`):** accounts, org units, VPCs/VNets, subnets,
  cloud interfaces (ENI/NIC), compute instances, security groups, network ACLs,
  route tables, gateways (IGW/NAT/VPN/TGW/DCGW), VPC peerings, load balancers,
  service endpoints, cloud firewalls, floating/public IPs.

## Nautobot models available (box: nautobot-ssot 4.4, cloud + virtualization apps present)

- **dcim:** Location, Device, DeviceType, Manufacturer, Platform, Interface,
  InventoryItem, Module/ModuleBay/ModuleType, Cable, Rack, …
- **ipam:** Prefix, IPAddress, VLAN, VLANGroup, VRF, Namespace, RouteTarget,
  Service, RIR, + association tables (VRFPrefixAssignment, IPAddressToInterface,
  VRFDeviceAssignment, VLANLocationAssignment).
- **cloud:** CloudAccount, CloudNetwork, CloudService, CloudResourceType,
  CloudNetworkPrefixAssignment, CloudServiceNetworkAssignment.
- **virtualization:** Cluster, VirtualMachine, VMInterface, ClusterType/Group.

## Mutual matrix (the import set)

| Forward source | Nautobot model | Status | Notes / required FKs |
|---|---|---|---|
| locations | dcim.Location | ✅ contrib | LocationType(+Device ct), Status |
| devices | dcim.Device | ✅ contrib | location, role, status, device_type, platform |
| platform.vendor | dcim.Manufacturer | ✅ contrib (derived) | — |
| platform.model | dcim.Platform | ✅ contrib (derived) | manufacturer |
| platform.deviceType | dcim.DeviceType | ✅ contrib (derived) | manufacturer + model |
| interfaces | dcim.Interface | ✅ contrib | device; type/enabled/mtu/desc |
| components (inventory) | dcim.InventoryItem | ✅ contrib | device; manufacturer |
| components (modules) | dcim.Module | ✅ contrib | ModuleType + ModuleBay derived; parent_module_bay |
| vlans | ipam.VLAN | ✅ contrib | status; (vid, name) identity |
| vrfs | ipam.VRF | ✅ contrib | namespace (Global) |
| FIB prefixes (v4/v6) | ipam.Prefix | ✅ contrib | network/prefix_length identity; namespace; status |
| interface IPs | ipam.IPAddress | ✅ contrib | host/mask_length identity; namespace; auto-parent |
| **cloudAccounts** | **cloud.CloudAccount** | 🟦 phase 3-cloud | name, account_number, provider→Manufacturer |
| **vpcs** | **cloud.CloudNetwork** | 🟦 phase 3-cloud | cloud_resource_type, cloud_account |
| **subnets** | **cloud.CloudNetwork** (parent=VPC) | 🟦 phase 3-cloud | + CloudNetworkPrefixAssignment for CIDRs |
| **loadBalancers/gateways** | **cloud.CloudService** | 🟦 phase 3-cloud | cloud_resource_type, cloud_account |
| compute instances | virtualization.VirtualMachine | later | cluster, status (needs ClusterType/Cluster) |
| security groups / firewall rules | (no first-class Nautobot model) | out | represent as CloudService extra_config or skip |
| BGP/OSPF, ACL/NAT, CVEs, hosts | (no core Nautobot model) | out | not mutually supported in core |

## Cloud prerequisites (contrib resolves FKs by lookup, never creates)

- **provider** = a `Manufacturer` per cloud type (AWS/Azure/GCP/IBM) — ensure up front.
- **CloudResourceType** per (provider, kind) e.g. "AWS VPC", "AWS Subnet",
  "AWS Load Balancer", with `content_types` linked to CloudNetwork / CloudService.
- CloudAccount.account_number is required (use the Forward account id).

## NQEs to author

- `forward_cloud_accounts.nqe` → CloudAccount
- `forward_cloud_networks.nqe` → CloudNetwork (VPCs; subnets as child rows)
- `forward_cloud_services.nqe` → CloudService (load balancers + gateways)

## Out of scope (no mutual model)

Security groups/ACLs/NAT/BGP/OSPF/CVEs/discovered-hosts have no first-class core
Nautobot model; carry the useful subset as `extra_config` on CloudService later,
or skip. Compute instances → VirtualMachine is feasible but needs a Cluster
scaffold; deferred behind the cloud-network/service slices.
