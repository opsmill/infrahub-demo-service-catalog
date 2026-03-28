# Research: L2/L3 Interface Mode Selection

**Feature**: 002-l2-l3-interface-mode | **Date**: 2026-03-17

## R1: IP-to-VLAN Relationship in Infrahub Schema

**Decision**: Add an optional `vlan` relationship on `IpamIPAddress` with a reverse `ip_addresses` on `IpamVLAN`, using identifier `vlan__ip_addresses`.

**Rationale**: The existing `IpamIPAddress` only has an `interface` relationship to `DcimInterfaceL3`. For L2 mode, the gateway IP must associate directly with the VLAN. The `interface` relationship on `IpamIPAddress` is already optional (`optional: true` in `schemas/base/ipam.yml`), so adding a parallel optional `vlan` relationship follows the same pattern. The reverse relationship is added via an extension in `schemas/vlan/vlan.yml` (consistent with how `untagged_vlan`/`tagged_vlan` are added to `DcimInterfaceL2` via extension).

**Alternatives considered**:

- Create gateway IP without any interface/VLAN link: Rejected — user explicitly requested IP-to-VLAN association
- Create an L3 SVI interface object on the router: Rejected — user wants the SVI rendered from VLAN data in the transform, not from an interface object

## R2: Device Config Transform for L2 SVI Rendering

**Decision**: Extend `templates/device_info.gql` to fetch `ip_addresses` within VLAN data, and extend `templates/device_config.j2` to render VLAN SVIs when a VLAN has associated IP addresses.

**Rationale**: The device config transform is data-driven (per-device). In L2 mode, no L3 interface object exists on the router, so the existing L3 interface rendering path produces nothing. The SVI must be rendered from VLAN data at the device's location. This approach is purely data-driven: any VLAN with IPs gets an SVI, which is correct for both new L2 services and any future use cases.

**Alternatives considered**:

- Have the generator create an L3 SVI interface object: Rejected — user chose the query/template extension approach to keep the data model clean
- Render SVI on core switch instead of edge router: Rejected — user chose edge router

## R3: Backward Compatibility with Default Value

**Decision**: Use `default_value: l3` on the `interface_mode` Dropdown attribute.

**Rationale**: Existing `ServiceDedicatedInternet` objects were all created as L3 services. Setting the default to `l3` means existing records automatically get the correct value without data migration. The generator also defaults to L3 behavior if the value is missing or invalid, providing defense in depth.

**Alternatives considered**: None — this is the standard Infrahub pattern for adding new attributes to existing nodes.
