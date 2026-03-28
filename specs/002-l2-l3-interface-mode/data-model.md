# Data Model: L2/L3 Interface Mode Selection

**Feature**: 002-l2-l3-interface-mode | **Date**: 2026-03-17

## Entity Changes

### ServiceDedicatedInternet (modified)

New attribute added:

| Attribute | Kind | Required | Default | Choices |
|-----------|------|----------|---------|---------|
| interface_mode | Dropdown | yes | l3 | l2 (Layer 2), l3 (Layer 3) |

Existing attributes and relationships unchanged.

### IpamIPAddress (modified)

New relationship added:

| Relationship | Peer | Cardinality | Optional | Identifier |
|-------------|------|-------------|----------|------------|
| vlan | IpamVLAN | one | yes | vlan__ip_addresses |

Existing relationships unchanged. The `interface` relationship (to `DcimInterfaceL3`) remains optional and is used for L3 mode. The new `vlan` relationship is used for L2 mode. Both are optional; an IP address may have one, the other, or neither.

### IpamVLAN (modified)

New reverse relationship added (via extension):

| Relationship | Peer | Cardinality | Optional | Identifier |
|-------------|------|-------------|----------|------------|
| ip_addresses | IpamIPAddress | many | yes | vlan__ip_addresses |

Existing relationships unchanged.

## State Transitions

No changes to service lifecycle states. The `interface_mode` is set at creation time and does not change during the service lifecycle (draft → in-delivery → active → in-decommissioning → decommissioned).

## Provisioning Paths

### L3 Mode (existing, default)

```text
ServiceDedicatedInternet (interface_mode=l3)
├── IpamVLAN (allocated from pool)
├── IpamPrefix (allocated from pool)
├── DcimInterfaceL2 (customer port on core switch)
│   └── untagged_vlan → IpamVLAN
├── DcimInterfaceL3 (gateway on edge router)   ← CREATED
│   └── ip_addresses → IpamIPAddress
└── IpamIPAddress (gateway IP)
    ├── interface → DcimInterfaceL3             ← LINKED TO INTERFACE
    └── service → ServiceDedicatedInternet
```

### L2 Mode (new)

```text
ServiceDedicatedInternet (interface_mode=l2)
├── IpamVLAN (allocated from pool)
│   └── ip_addresses → IpamIPAddress            ← NEW REVERSE LINK
├── IpamPrefix (allocated from pool)
├── DcimInterfaceL2 (customer port on core switch)
│   └── untagged_vlan → IpamVLAN
└── IpamIPAddress (gateway IP)
    ├── vlan → IpamVLAN                          ← LINKED TO VLAN
    └── service → ServiceDedicatedInternet
                                                  (no DcimInterfaceL3 created)
```

## Schema Files

| File | Change |
|------|--------|
| `schemas/service/service.yml` | Add `interface_mode` dropdown to ServiceDedicatedInternet |
| `schemas/base/ipam.yml` | Add `vlan` relationship to IpamIPAddress |
| `schemas/vlan/vlan.yml` | Add `ip_addresses` reverse relationship extension to IpamVLAN |
