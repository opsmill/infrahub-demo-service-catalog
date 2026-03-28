# Quickstart: L2/L3 Interface Mode Selection

**Feature**: 002-l2-l3-interface-mode | **Date**: 2026-03-17

## What Changed

The Dedicated Internet service now supports two interface modes:

- **Layer 3** (default): Gateway IP on a dedicated L3 interface on the edge router (existing behavior)
- **Layer 2** (new): Gateway IP linked to the VLAN, SVI rendered in device config from VLAN data

## How to Test

### 1. Validate schemas

```bash
uv run infrahubctl schema check schemas/
```

### 2. Run linters

```bash
invoke lint
```

### 3. Run tests

```bash
uv run pytest
```

### 4. Manual verification (requires running Infrahub instance)

1. Start the stack: `invoke start`
2. Open the Streamlit portal
3. Navigate to Dedicated Internet page
4. Verify the "Interface Mode" selector appears with Layer 2 and Layer 3 options
5. Submit an L2 service request and verify:
   - VLAN is allocated
   - IP prefix is allocated
   - L2 port is configured on core switch
   - Gateway IP is linked to VLAN (not to an interface)
   - No L3 interface is created on edge router
   - Startup config artifact for the edge router shows a VLAN SVI with the gateway IP
6. Submit an L3 service request and verify behavior is unchanged from before

## Files Modified

| File | Purpose |
|------|---------|
| `schemas/service/service.yml` | Added `interface_mode` dropdown |
| `schemas/base/ipam.yml` | Added `vlan` relationship on IpamIPAddress |
| `schemas/vlan/vlan.yml` | Added `ip_addresses` reverse relationship on IpamVLAN |
| `generators/implement_dedicated_internet.py` | Conditional L2/L3 gateway logic |
| `generators/protocols.py` | Protocol type updates |
| `generators/dedicated_internet.gql` | Added `interface_mode` to query |
| `service_catalog/pages/1_🔌_Dedicated_Internet.py` | Added mode selector to form |
| `service_catalog/protocols_sync.py` | Protocol type updates |
| `templates/device_config.j2` | SVI rendering from VLAN IP data |
| `templates/device_info.gql` | Added `ip_addresses` to VLAN query |
