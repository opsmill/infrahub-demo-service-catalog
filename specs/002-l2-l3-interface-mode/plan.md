# Implementation Plan: L2/L3 Interface Mode Selection

**Branch**: `002-l2-l3-interface-mode` | **Date**: 2026-03-17 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-l2-l3-interface-mode/spec.md`

## Summary

Add an `interface_mode` dropdown (L2/L3) to the Dedicated Internet service. In L3 mode (default, existing behavior), a dedicated L3 gateway interface is created on the edge router with the gateway IP. In L2 mode, the gateway IP is linked directly to the VLAN via a new IP-to-VLAN schema relationship, no L3 interface is created, and the device config transform renders an SVI from VLAN IP data.

## Technical Context

**Language/Version**: Python >=3.10, <3.13
**Primary Dependencies**: infrahub-sdk, streamlit, fast-depends
**Storage**: Infrahub (GraphQL API, branch-based change management)
**Testing**: pytest, pytest-asyncio, infrahub-testcontainers
**Target Platform**: Docker containers (Streamlit portal + Infrahub)
**Project Type**: Service catalog demo (web-service + generators + transforms)
**Performance Goals**: N/A (demo project)
**Constraints**: All data operations through Infrahub SDK; schemas validated with `infrahubctl schema check`
**Scale/Scope**: Adding 1 attribute, 1 schema relationship, modifying 1 generator, 1 form, 1 transform

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Infrahub-First | PASS | All changes use Infrahub SDK, schemas, GraphQL queries, and pool mechanisms |
| II. Type Safety | PASS | New `interface_mode` attribute will have Dropdown type in protocols; all functions typed |
| III. Test Discipline | PASS | Existing tests must pass; unit test updates for generator L2 path |
| IV. Service Lifecycle Integrity | PASS | L2 mode follows same lifecycle (draft→active); resource allocation completes before transition |
| V. Simplicity & YAGNI | PASS | Minimal changes: 1 new attribute, 1 new relationship, conditional branch in generator |

No violations. No Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/002-l2-l3-interface-mode/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (files to modify)

```text
schemas/
├── service/service.yml          # Add interface_mode attribute to ServiceDedicatedInternet
├── base/ipam.yml                # Add vlan relationship to IpamIPAddress
└── vlan/vlan.yml                # Add ip_addresses extension for IpamVLAN

generators/
├── implement_dedicated_internet.py  # Conditional L2/L3 gateway logic
├── protocols.py                     # Add interface_mode to ServiceDedicatedInternet, vlan to IpamIPAddress
└── dedicated_internet.gql           # Add interface_mode field

service_catalog/
├── pages/1_🔌_Dedicated_Internet.py  # Add interface mode selector
└── protocols_sync.py                  # Add interface_mode to ServiceDedicatedInternet

templates/
├── device_config.j2              # Add SVI rendering from VLAN IP data
└── device_info.gql               # Add ip_addresses to VLAN query
```

**Structure Decision**: No new files or directories. All changes are modifications to existing files in the established project structure.

## Implementation Details

### Step 1: Schema Changes

#### 1a. Add `interface_mode` to ServiceDedicatedInternet

**File**: `schemas/service/service.yml`

Add after `ip_package` (order_weight 1120):

```yaml
      - name: interface_mode
        kind: Dropdown
        optional: false
        default_value: l3
        order_weight: 1130
        branch: aware
        choices:
          - name: l3
            label: Layer 3
            description: Gateway IP assigned to a dedicated L3 interface on the edge router.
            color: "#6a5acd"
          - name: l2
            label: Layer 2
            description: Gateway IP associated with the VLAN. SVI rendered on edge router from VLAN data.
            color: "#9090de"
```

#### 1b. Add `vlan` relationship to IpamIPAddress

**File**: `schemas/base/ipam.yml`

Add to `IpamIPAddress` relationships (after `interface`):

```yaml
      - name: vlan
        peer: IpamVLAN
        optional: true
        cardinality: one
        kind: Attribute
        identifier: vlan__ip_addresses
```

#### 1c. Add reverse relationship extension for VLAN

**File**: `schemas/vlan/vlan.yml`

Add extension for `IpamIPAddress`:

```yaml
    - kind: IpamVLAN
      relationships:
        - name: ip_addresses
          peer: IpamIPAddress
          optional: true
          cardinality: many
          identifier: vlan__ip_addresses
```

### Step 2: Protocol Updates

#### 2a. Generator protocols

**File**: `generators/protocols.py`

- Add `interface_mode: Dropdown` to `ServiceDedicatedInternet` class (line ~208)
- Add `vlan: RelatedNode` to `IpamIPAddress` class (line ~154)

#### 2b. Sync protocols

**File**: `service_catalog/protocols_sync.py`

- Add `interface_mode: Dropdown` to `ServiceDedicatedInternet` class (line ~158)

### Step 3: GraphQL Query Updates

#### 3a. Generator query

**File**: `generators/dedicated_internet.gql`

Add after `ip_package` block (line ~18):

```graphql
        interface_mode {
          value
        }
```

#### 3b. Device info query

**File**: `templates/device_info.gql`

Extend VLAN query within `location.node.vlans.edges.node` to include IP addresses:

```graphql
                  ip_addresses {
                    edges {
                      node {
                        address {
                          ip
                        }
                      }
                    }
                  }
```

### Step 4: Generator Logic

**File**: `generators/implement_dedicated_internet.py`

#### 4a. Conditional gateway in `generate()` method

Replace `await self.allocate_gateway()` with:

```python
        if self.customer_service.interface_mode.value == "l3":
            await self.allocate_gateway()
        else:
            await self.allocate_gateway_l2()
```

#### 4b. New `allocate_gateway_l2()` method

Creates gateway IP linked to VLAN (not to an interface):

- Compute gateway IP from prefix (same formula as L3)
- Create `IpamIPAddress` with `vlan=self.allocated_vlan` and `service=self.customer_service` (no `interface=`)
- Set as prefix gateway
- Save prefix

Key difference from `allocate_gateway()`: no `DcimInterfaceL3` created, IP linked to VLAN instead of interface.

### Step 5: Streamlit Form

**File**: `service_catalog/pages/1_🔌_Dedicated_Internet.py`

- Add interface mode selector (using existing `get_dropdown_options` helper) between bandwidth and IP package sections
- Include `interface_mode` in the service creation dict

### Step 6: Device Config Transform

#### 6a. Template update

**File**: `templates/device_config.j2`

After the existing VLAN configuration section (lines 7-12), add SVI rendering:

```jinja2
! VLAN Interface (SVI) Configuration
{% if device.location and device.location.node and device.location.node.vlans and device.location.node.vlans.edges %}
{% for vlan in device.location.node.vlans.edges %}
{% if vlan.node.ip_addresses and vlan.node.ip_addresses.edges %}
interface vlan {{ vlan.node.vlan_id.value }}
  {% for ip_addr in vlan.node.ip_addresses.edges %}
  {% if ip_addr.node and ip_addr.node.address and ip_addr.node.address.ip %}
  ip address {{ ip_addr.node.address.ip }}
  {% endif %}
  {% endfor %}
{% endif %}
{% endfor %}
{% endif %}
```

This is data-driven: any VLAN with IP addresses gets an SVI. VLANs without IPs are skipped.

## Verification

1. **Schema validation**: `uv run infrahubctl schema check schemas/`
2. **Linting**: `invoke lint` (ruff, mypy, yamllint)
3. **Tests**: `uv run pytest`
4. **Manual verification**:
   - Verify L3 mode produces identical results to current behavior
   - Verify L2 mode creates VLAN+IP link without L3 interface
   - Verify generated config for edge router includes SVI for L2 services
   - Verify generated config for L3 services is unchanged

## Complexity Tracking

> No violations detected. Table not needed.
