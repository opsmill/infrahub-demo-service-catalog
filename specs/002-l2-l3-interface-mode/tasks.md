# Tasks: L2/L3 Interface Mode Selection for Dedicated Internet Service

**Input**: Design documents from `/specs/002-l2-l3-interface-mode/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md

**Tests**: Not explicitly requested in feature spec. Tests omitted.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Schema & Data Model Foundation)

**Purpose**: Schema changes and protocol updates that all user stories depend on

- [x] T001 [P] Add `interface_mode` dropdown attribute to ServiceDedicatedInternet in `schemas/service/service.yml` (after `ip_package`, order_weight 1130, default l3, choices: l2/l3)
- [x] T002 [P] Add `vlan` relationship to IpamIPAddress in `schemas/base/ipam.yml` (optional, cardinality one, peer IpamVLAN, identifier vlan__ip_addresses)
- [x] T003 [P] Add `ip_addresses` reverse relationship extension on IpamVLAN in `schemas/vlan/vlan.yml` (optional, cardinality many, peer IpamIPAddress, identifier vlan__ip_addresses)
- [x] T004 Validate schemas with `uv run infrahubctl schema check schemas/`

---

## Phase 2: Foundational (Protocol & Query Updates)

**Purpose**: Type definitions and GraphQL queries that MUST be complete before generator/portal/transform work

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 [P] Add `interface_mode: Dropdown` to ServiceDedicatedInternet and `vlan: RelatedNode` to IpamIPAddress in `generators/protocols.py`
- [x] T006 [P] Add `interface_mode: Dropdown` to ServiceDedicatedInternet in `service_catalog/protocols_sync.py`
- [x] T007 [P] Add `interface_mode { value }` field to generator query in `generators/dedicated_internet.gql` (after `ip_package` block)
- [x] T008 [P] Add `ip_addresses` to VLAN query in `templates/device_info.gql` (inside `location.node.vlans.edges.node`, add `ip_addresses { edges { node { address { ip } } } }`)
- [x] T009 Run linters with `invoke lint` to verify protocol and query changes

**Checkpoint**: Foundation ready — all schemas, protocols, and queries updated. User story implementation can begin.

---

## Phase 3: User Story 1 — L3 Backward Compatibility (Priority: P1) 🎯 MVP

**Goal**: Existing L3 behavior continues to work with the new `interface_mode` attribute defaulting to `l3`

**Independent Test**: Submit a dedicated internet request with L3 mode and verify all existing resource allocations (VLAN, prefix, L2 port, L3 gateway interface with IP) are unchanged.

### Implementation for User Story 1

- [x] T010 [US1] Add conditional gateway logic in `generate()` method of `generators/implement_dedicated_internet.py` — branch on `self.customer_service.interface_mode.value`: if `"l3"` call existing `allocate_gateway()`, else call new `allocate_gateway_l2()` (stub for now)
- [x] T011 [US1] Verify existing tests pass with `uv run pytest` (L3 path must remain unchanged)

**Checkpoint**: L3 mode works identically to before. Existing services default to L3. All existing tests pass.

---

## Phase 4: User Story 2 — L2 Dedicated Internet Provisioning (Priority: P1)

**Goal**: When L2 mode is selected, the generator creates the gateway IP linked to the VLAN with no L3 interface on the edge router

**Independent Test**: Submit L2 request and verify: VLAN allocated, prefix allocated, L2 port configured, gateway IP linked to VLAN, no L3 interface created.

### Implementation for User Story 2

- [x] T012 [US2] Implement `allocate_gateway_l2()` method in `generators/implement_dedicated_internet.py` — compute gateway IP from prefix, create IpamIPAddress with `vlan=self.allocated_vlan` (no `interface=`), set as prefix gateway, save

**Checkpoint**: L2 provisioning path fully functional. Gateway IP links to VLAN, no L3 interface created.

---

## Phase 5: User Story 3 — Portal Interface Mode Selection (Priority: P1)

**Goal**: The Streamlit form includes an "Interface Mode" selector and passes the value to the service creation

**Independent Test**: Load the dedicated internet form, verify the selector appears with L2/L3 options, submit with L2 selected and verify the service object has `interface_mode=l2`.

### Implementation for User Story 3

- [x] T013 [US3] Add interface mode selectbox to the dedicated internet form in `service_catalog/pages/1_🔌_Dedicated_Internet.py` — use existing `get_dropdown_options` helper, place between bandwidth and IP package sections, include `interface_mode` in service creation dict

**Checkpoint**: Portal allows L2/L3 selection. Service objects are created with the correct interface_mode value.

---

## Phase 6: User Story 4 — Startup Config SVI Rendering (Priority: P1)

**Goal**: The device config transform renders VLAN SVIs with IP addresses for L2 services on edge routers

**Independent Test**: Provision an L2 service, generate startup config for the edge router, verify it contains `interface vlan <id>` with the gateway IP.

### Implementation for User Story 4

- [x] T014 [US4] Add SVI rendering section to `templates/device_config.j2` — after VLAN configuration section (line 12), iterate VLANs at device location, render `interface vlan <vlan_id>` with IP addresses for VLANs that have associated IPs

**Checkpoint**: Edge router config includes VLAN SVIs for L2 services. L3 service configs unchanged.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation across all stories

- [x] T015 Run schema validation with `uv run infrahubctl schema check schemas/`
- [x] T016 Run full linter suite with `invoke lint`
- [x] T017 Run full test suite with `uv run pytest`
- [x] T018 Run quickstart.md validation steps from `specs/002-l2-l3-interface-mode/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately. T001-T003 are parallel (different files). T004 depends on T001-T003.
- **Foundational (Phase 2)**: Depends on Phase 1 completion. T005-T008 are parallel (different files). T009 depends on T005-T008.
- **User Stories (Phases 3-6)**: All depend on Phase 2 completion.
    - US1 (L3 backward compat): Can start after Phase 2
    - US2 (L2 provisioning): Can start after Phase 2, but logically follows US1 (T010 creates the conditional branch, T012 fills in the L2 path)
    - US3 (Portal): Can start after Phase 2, independent of US1/US2 (different file)
    - US4 (Transform): Can start after Phase 2, independent of US1/US2/US3 (different files)
- **Polish (Phase 7)**: Depends on all user stories being complete.

### User Story Dependencies

- **User Story 1 (L3 compat)**: After Phase 2. No other story dependencies.
- **User Story 2 (L2 provisioning)**: After US1 (T010 creates the conditional branch that T012 fills in).
- **User Story 3 (Portal)**: After Phase 2. Independent of US1/US2 (different file: Streamlit page).
- **User Story 4 (Transform)**: After Phase 2. Independent of US1/US2/US3 (different files: Jinja2 template).

### Parallel Opportunities

- **Phase 1**: T001, T002, T003 can all run in parallel (different schema files)
- **Phase 2**: T005, T006, T007, T008 can all run in parallel (different files)
- **User Stories**: US3 (portal) and US4 (transform) can run in parallel with US1/US2 (different files)

---

## Parallel Example: Setup Phase

```bash
# Launch all schema changes together (different files):
Task: "Add interface_mode to ServiceDedicatedInternet in schemas/service/service.yml"
Task: "Add vlan relationship to IpamIPAddress in schemas/base/ipam.yml"
Task: "Add ip_addresses extension on IpamVLAN in schemas/vlan/vlan.yml"
```

## Parallel Example: Foundational Phase

```bash
# Launch all protocol and query updates together (different files):
Task: "Update generators/protocols.py"
Task: "Update service_catalog/protocols_sync.py"
Task: "Update generators/dedicated_internet.gql"
Task: "Update templates/device_info.gql"
```

## Parallel Example: User Stories 3 & 4

```bash
# These can run in parallel after Phase 2 (different files, no dependencies):
Task: "Add interface mode selectbox in service_catalog/pages/1_🔌_Dedicated_Internet.py"
Task: "Add SVI rendering in templates/device_config.j2"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Schema changes (3 files, parallel)
2. Complete Phase 2: Protocols & queries (4 files, parallel)
3. Complete Phase 3: US1 — L3 backward compatibility (verify nothing breaks)
4. Complete Phase 4: US2 — L2 provisioning (new `allocate_gateway_l2` method)
5. **STOP and VALIDATE**: Both L2 and L3 provisioning paths work

### Full Delivery

6. Complete Phase 5: US3 — Portal selector (enables user access to L2 mode)
7. Complete Phase 6: US4 — Transform SVI rendering (generates correct configs)
8. Complete Phase 7: Polish (final validation)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
