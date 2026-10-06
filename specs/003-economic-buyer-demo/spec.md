# Feature Specification: Economic Buyer Demo ("Can I safely take this router down?")

**Feature Branch**: `003-economic-buyer-demo`
**Created**: 2026-10-03
**Status**: Draft
**Input**: User description: "Economic buyer demo for the Service Catalog: can I safely take this router down for maintenance? Let presales show an economic buyer (CTO, VP Infrastructure, CFO) how Infrahub connects business context (customers, service tiers, contract value) to infrastructure, finds hidden risk, and blocks risky changes before they reach production, using only defensible numbers. Extends the existing Service Catalog demo; does not replace the requester flow."

## Context and Intent

The current demo proves the technical flow well: a service request becomes infrastructure, is reviewed as a proposed change, and is deployed. It speaks to engineers. An economic buyer asks different questions:

- What does this piece of infrastructure matter to, in business terms?
- Are we delivering what we promised our most valuable customers?
- Can I make this change without putting that at risk?

This feature adds a thin business layer (customers, service tiers, contract value) to the same model the demo already uses, and one storyline built on it. The goal is a live, defensible answer to "Can I safely take router `rb01-par01` down for maintenance?" Every number shown must be traceable to the model or to a clearly labeled business input. No invented ROI.

The feature serves two capabilities from the broader economic story:

- **Unification**: business context and infrastructure in one model you can query.
- **Control**: a proposed change is checked against service intent before it becomes real.

Integration (syncing external systems) and Acceleration (reusing context across automations) stay on slides for this version.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Risky maintenance is blocked before it happens (Priority: P1)

A presenter shows that planning maintenance on an edge router, which looks harmless, would break the promise made to a Gold customer. The proposed change fails its intent check and cannot be merged. The failure message names the customer, the tier, and the contract value involved.

**Why this priority**: This is the one moment slides cannot fake. A live, blocked change is proof; a slide saying "this would have been caught" is a claim. Without it, the rest of the storyline has no punchline.

**Independent Test**: Load the seed data, open a branch that puts `rb01-par01` into maintenance, open a proposed change, and confirm the intent check fails with the expected customer, tier and value. Then fix the affected service in the branch and confirm the check passes.

**Acceptance Scenarios**:

1. **Given** the seeded network where the Northbank Gold service has both paths on `rb01-par01`, **When** a proposed change sets `rb01-par01` to maintenance, **Then** the intent check fails because Northbank would have no path in service, and the message names Northbank, Gold tier, and its annual contract value.
2. **Given** the same network, **When** a proposed change sets `rb02-par01` to maintenance, **Then** the intent check passes with a warning that Helix Health runs on one path during the maintenance (reduced redundancy), and Northbank's existing design flaw is reported as a warning only.
3. **Given** a failing proposed change, **When** the presenter moves Northbank's second path to `rb02-par01` within the same branch, **Then** the intent check passes (with a reduced-redundancy warning for the maintenance itself) and the change can be merged.
4. **Given** a merged fix, **When** the deployment step runs, **Then** updated device configurations are generated and deployed through the existing automation, as the demo does today.

---

### User Story 2 - Economic buyer sees business exposure of the network (Priority: P2)

A presenter opens a Business Impact view and answers "What does this router matter to?" The view shows portfolio totals, routers ranked by the Gold contract value that depends on them, the services behind a selected router, and current intent violations. Each number is labeled with its source.

**Why this priority**: This is the Unification story and sets up User Story 1. It is useful on its own: it reveals the hidden single point of failure in today's network before any change is proposed.

**Independent Test**: With seed data loaded, open the view, select `rb01-par01`, and confirm the services, customers, tiers, contract values and violation shown match the seed data and the formulas in this spec.

**Acceptance Scenarios**:

1. **Given** seed data on the current network, **When** the viewer opens the Business Impact view, **Then** it shows four portfolio figures: annual contract value, Gold services with a design flaw, Gold services with no path in service, and Gold contract value at risk.
2. **Given** the view is open, **When** the viewer looks at the router ranking, **Then** edge routers are listed in descending order of the annual Gold contract value that depends on them, with service count and violation count per router.
3. **Given** the viewer selects `rb01-par01`, **When** the blast radius section loads, **Then** it lists every service with a path on that router, with customer, tier, monthly charge, number of separate paths, and intent status.
4. **Given** the viewer enters a maintenance window in minutes, **When** the value changes, **Then** each affected tier shows whether that window fits within its allowed monthly downtime.
5. **Given** any number on the view, **When** the viewer asks where it comes from (hover or info marker), **Then** the formula and its source label (A or B) are shown.
6. **Given** the intent violations list, **When** the viewer selects a violation, **Then** they can open the affected service in Infrahub.

---

### User Story 3 - Compare a proposed change against today (Priority: P3)

A presenter switches the Business Impact view from "current network" to a proposed change. All figures recalculate for the proposed state and show the difference from today, so the buyer sees the effect of the change at a glance.

**Why this priority**: This is what a static inventory report cannot do: show the future state before it exists. It links the buyer view (Story 2) to the blocked change (Story 1). It depends on both, so it comes third.

**Independent Test**: Create the `rb01-par01` maintenance branch, select it in the view, and confirm "Gold services with no path" changes from 0 to 1 with the difference shown.

**Acceptance Scenarios**:

1. **Given** a branch with `rb01-par01` in maintenance, **When** the viewer selects that branch, **Then** portfolio figures show their value in that branch and the change compared with the current network (Gold services with no path: 0 to 1).
2. **Given** the viewer switches back to the current network, **When** the view reloads, **Then** figures match the current network with no differences shown.
3. **Given** the maintenance branch with the Northbank fix applied, **When** the viewer selects it, **Then** Gold services with a design flaw drop from 1 to 0, Gold services with no path are 0, and Gold contract value at risk drops to €0.

---

### User Story 4 - Ordering shows tier and price (Priority: P4)

A requester ordering Dedicated Internet picks a customer and a service tier, and sees a monthly price quote before submitting. A Gold order is delivered with two separate paths on different switches and different edge routers at the site. Silver and Bronze orders behave as today.

**Why this priority**: It ties the business layer back to the existing requester flow and shows that provisioning respects intent by design. The storyline can run without it, so it ranks below the impact and control stories.

**Independent Test**: Order a 1 Gbps Gold service at `par01` and confirm the quote shows €2,160 per month, and that the delivered service has paths on two different switches and two different edge routers.

**Acceptance Scenarios**:

1. **Given** the order form, **When** the requester picks bandwidth and tier, **Then** the form shows the monthly price from the price list before submission.
2. **Given** a Gold order, **When** provisioning completes, **Then** the service has two paths that share no switch and no edge router.
3. **Given** a Silver or Bronze order, **When** provisioning completes, **Then** the service has one path, as today.
4. **Given** a Gold order at a site with fewer than two free ports on separate switches or fewer than two edge routers, **When** provisioning runs, **Then** it stops with a clear message and does not create a single-path Gold service.

---

### User Story 5 - Presenters can run the story consistently (Priority: P5)

A presales engineer who did not build the demo can run the full storyline from a written talk track, and knows which claims are safe to make.

**Why this priority**: The demo only creates value if the field can repeat it. It is documentation, so it is cheap, but it depends on the stories above being real.

**Independent Test**: A presales engineer new to the feature runs steps 1 to 5 of the talk track live, using only the written material, within 12 minutes.

**Acceptance Scenarios**:

1. **Given** the talk track, **When** a presenter follows it, **Then** it covers: what the router matters to, what was promised, whether we deliver, the blocked maintenance, the fix, the passing check, merge and deploy.
2. **Given** the "claims we make / claims we don't make" list, **When** a presenter reviews it, **Then** each allowed claim maps to a number shown in the demo, and each disallowed claim says why.

---

### Edge Cases

- **Pre-existing design flaws on the current network**: Northbank already has a design flaw today. The intent check must not fail every unrelated proposed change (for example, a new Bronze order) because of it. Pre-existing, unchanged design flaws are reported as warnings.
- **Routine maintenance on a properly redundant Gold service**: losing one of two paths during maintenance is what redundancy is for. It is a warning (reduced redundancy), not a failure, or no maintenance could ever pass.
- **Router already in maintenance on the current network**: services with a path on it count that path as out of service everywhere (view and check).
- **Both edge routers at a site in maintenance in one branch**: every Gold service at that site is reported, each once.
- **Service with no tier or no customer** (for example, created before this feature): treated as Bronze with no contract value, shown as "unassigned" and excluded from Gold totals.
- **Maintenance window of zero or empty**: the blast radius shows allowed downtime per tier without a fits/exceeds verdict.
- **Branch with no business-relevant changes**: the view shows the same figures as the current network with zero differences.
- **Service in draft or decommissioned state**: excluded from contract value totals and intent evaluation.
- **Viewer opens the view before seed data exists**: the view says no services are found instead of showing zeros as if they were results.

## Requirements *(mandatory)*

### Functional Requirements

**Business model**

- **FR-001**: The model MUST represent customers, each with a name, and link every Dedicated Internet service to one customer. The existing account reference MUST remain so nothing currently working breaks.
- **FR-002**: The model MUST represent service tiers (Gold, Silver, Bronze), each with an availability target, a minimum number of separate paths, and an SLA credit percentage. Values: Gold 99.99% / 2 / 25%, Silver 99.9% / 1 / 10%, Bronze 99.5% / 1 / 5%.
- **FR-003**: Every Dedicated Internet service MUST carry a tier and a monthly charge.
- **FR-004**: The monthly charge MUST follow the price list: base price by bandwidth (100 Mbps €400, 1 Gbps €1,200, 10 Gbps €4,500) times tier multiplier (Bronze 1.0, Silver 1.3, Gold 1.8).
- **FR-005**: Business inputs (prices, tier values, contract value) MUST be marked as demo business inputs wherever they appear, so no viewer mistakes them for figures calculated by Infrahub.

**Provisioning**

- **FR-006**: The order form MUST let the requester choose a customer and a tier, and MUST show the monthly price before submission.
- **FR-007**: A Gold service MUST be delivered with two paths that share no switch and no edge router.
- **FR-008**: Silver and Bronze services MUST be delivered with one path, as today.
- **FR-009**: If a Gold service cannot get two separate paths, provisioning MUST stop with a clear message rather than deliver a single-path Gold service.

**Seed data**

- **FR-010**: The demo MUST ship with seed data for 4 customers (Northbank, Gold; Helix Health, Gold; Maison Verte, Silver; Rapid Freight, Bronze) and 12 to 15 services across `par01` and `bru01`.
- **FR-011**: Seed data MUST include exactly one deliberate hidden single point of failure: the Northbank 10 Gbps Gold service with both paths on `rb01-par01`.
- **FR-012**: Seeded services MUST look exactly like services delivered through the normal ordering flow (same resources and relationships), apart from the one deliberate violation.
- **FR-013**: Loading seed data MUST be part of the standard demo setup and MUST give the same result every time it runs from a clean start.

**Intent check**

- **FR-014**: Every proposed change MUST run an intent check that gives each active service one intent status, using the worst that applies:
    - **No path**: no edge router on its paths is in service.
    - **Design flaw**: its paths use fewer separate edge routers than the tier minimum, whatever their status (a hidden single point of failure).
    - **Reduced redundancy**: fewer separate in-service edge routers than the tier minimum, but at least one.
    - **Meets intent**: none of the above.
- **FR-015**: The intent check MUST fail when the change gives a Gold service the status "No path" or introduces a new "Design flaw" for any service. "Reduced redundancy" and design flaws already present on the current network and unchanged by the change MUST be reported as warnings only. Silver and Bronze services reaching "No path" during planned maintenance MUST NOT fail or warn in the check; they appear in the Business Impact view only (FR-023), because planned maintenance is excluded from their SLA.
- **FR-016**: Each failure or warning message MUST name the service, customer, tier, required vs. actual number of separate paths, and the service's annual contract value labeled as a business input.
- **FR-017**: A failing intent check MUST block the merge of the proposed change.
- **FR-018**: Router maintenance MUST be represented by changing the router's status to maintenance or drained in a branch. Both statuses count as out of service.
- **FR-018a**: The live fix for a design flaw MUST be possible by hand in the Infrahub UI, within the failing branch: move the second path's gateway from the shared edge router to the other edge router at the site. The intent check then re-runs on the proposed change. No automated repair is required for V1.

**Business Impact view**

- **FR-019**: The view MUST let the viewer pick the current network or any open branch, and MUST show all figures for that choice.
- **FR-020**: When a branch is selected, each portfolio figure MUST show its difference from the current network.
- **FR-021**: The portfolio section MUST show exactly four figures: annual contract value, Gold services with a design flaw, Gold services with no path, and Gold contract value at risk.
- **FR-022**: The view MUST rank edge routers by the annual contract value of Gold services with a path on them, showing service and violation counts.
- **FR-023**: For a selected router, the view MUST list each service with a path on it: service identifier, customer, tier, monthly charge, number of separate in-service paths, and intent status.
- **FR-024**: The view MUST accept a maintenance window in minutes and show, for each tier present, whether that window fits within the tier's allowed monthly downtime (Gold 4.3 min, Silver 43 min, Bronze 3.6 h, based on a 30-day month). Silver and Bronze rows MUST state that planned maintenance is excluded from their SLA, so the comparison reads as "if this were unplanned". For Gold, the comparison applies directly, because the Gold promise includes maintenance without downtime.
- **FR-025**: The view MUST list every service whose intent status is not "Meets intent" for the selected network state, worst first, each linking to the service in Infrahub.
- **FR-026**: Every number on the view MUST carry a source label: **A** (counted from the model) or **B** (model combined with a labeled business input), and MUST show its formula on request.
- **FR-027**: The view MUST include a footer stating what it does not calculate: outage cost, time saved, ROI, churn.
- **FR-028**: The view MUST NOT show trend charts, outage cost, time saved, ROI, or churn figures.
- **FR-029**: Money MUST be described as contract value "associated" or "at risk", never as loss or cost of an outage.

**Presenter material**

- **FR-030**: The feature MUST include a written talk track for the 10-minute storyline.
- **FR-031**: The feature MUST include a "claims we make / claims we don't make" list. Each allowed claim maps to a figure in the demo; each disallowed claim states why.
- **FR-032**: The existing requester flow (order, branch, proposed change, merge, deploy) MUST keep working for presenters who do not use the economic buyer storyline.

### Figure definitions

| Figure | Source | Formula |
|---|---|---|
| Services on a router | A | Active services with at least one path on the router |
| Customers on a router | A | Distinct customers of those services |
| Gold services | A | Active services with tier Gold |
| Separate paths (design) | A | Distinct edge routers on a service's paths, any status |
| Separate paths in service | A | Distinct edge routers with status active on a service's paths |
| Intent status | A | Worst of No path / Design flaw / Reduced redundancy / Meets intent (FR-014) |
| Gold services with a design flaw | A | Gold services whose design paths are below the tier minimum |
| Gold services with no path | A | Gold services with zero separate paths in service |
| Monthly charge | B | Price list (FR-004) |
| Annual contract value | B | Sum of monthly charges of active services × 12 |
| Gold contract value on a router | B | Sum of monthly charges of Gold services on the router × 12 |
| Gold contract value at risk | B | Sum of monthly charges of Gold services with status No path or Design flaw × 12 |
| SLA credit if breached | B | Tier credit % × monthly charge |
| Allowed monthly downtime | B | (1 − availability target) × 43,200 minutes |

### Key Entities

- **Customer**: a buyer of services. Has a name. Linked to one or more services.
- **Service Tier**: the promise made to a customer. Has availability target, minimum separate paths, and SLA credit percentage. Gold, Silver, Bronze.
- **Dedicated Internet Service** (existing): gains a link to its customer and tier, and a monthly charge. Keeps its existing links to site, interfaces, VLAN, prefix and gateway address.
- **Path**: the route from a service to the network, through a switch port and an edge router. Not a new object in the model; derived from the service's existing interface and gateway relationships.
- **Edge Router** (existing device): its status (active, maintenance, drained) decides whether paths through it count as in service.
- **Intent Status**: a derived result, not stored: No path, Design flaw, Reduced redundancy, or Meets intent (FR-014).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The field CTO confirms that "Can I safely take this router down?" (or a close variant) is a question they hear from CTO or VP Infrastructure buyers, before implementation starts.
- **SC-002**: A presales engineer new to the feature runs storyline steps 1 to 5 live in under 12 minutes, using only the talk track.
- **SC-003**: 100% of figures shown on the Business Impact view can be traced, by a viewer, to either the model (A) or a labeled business input (B) through the formula shown on screen.
- **SC-004**: The blocked-maintenance scenario produces the same result (fail, then pass after the fix) in 10 out of 10 runs from a clean demo setup.
- **SC-005**: Switching the view between current network and a branch shows updated figures in under 3 seconds with seed data loaded.
- **SC-006**: The existing requester flow passes its current tests unchanged.
- **SC-007**: In a review by the field CTO, no on-screen figure or talk-track claim is flagged as unsupported.

## Assumptions

- **ISP framing**: the demo stays an ISP selling Dedicated Internet to customers. Contract value comes from monthly charges, not from "revenue attributed to a business service".
- **Prices and tier values are demo inputs**: they are plausible, not market data, and will be checked with the field CTO before release.
- **Currency**: euros across all sites, including US sites, for simplicity.
- **Planned maintenance and SLAs**: announced maintenance is excluded from Silver and Bronze SLAs. Gold customers pay for redundancy so that maintenance causes no downtime.
- **Device status**: the existing device status already includes maintenance and drained; no new status is needed.
- **Paths derived, not modeled**: separate paths come from existing relationships (service to interfaces to devices, and gateway to edge router). No dependency object is added.
- **Topology**: each site keeps its current 2 switches and 2 edge routers. No circuits are needed for V1.
- **Seeding**: seed services are created through the same ordering and provisioning flow as real orders. The one deliberate violation is applied as a follow-up change after normal provisioning.
- **Viewers**: the Business Impact view is read-only and has no extra permissions beyond what the portal has today.
- **Effort**: rough estimate 1.5 to 2 weeks. Dual-path Gold provisioning is the largest and least certain piece.

## Out of Scope

- Separate requirement objects (availability, capacity, resilience, geography, compliance) and RTO/RPO
- A dedicated infrastructure dependency object
- Cost allocation, infrastructure cost, and telemetry or utilization data
- Modeling automation workflows or computing a context reuse ratio (slide only)
- AI agent scenario using the Infrahub MCP server (phase 2)
- Infrahub Sync integrations with CRM, ERP, ITSM or monitoring (slide only)
- ROI worksheet or business case calculator
- Renaming the demo

## Clarifications

### Session 2026-10-03

- Q: Should Silver or Bronze services that lose their only path during planned maintenance fail the check, warn, or only show in the view? → A: Only show in the view. Planned maintenance is excluded from Silver and Bronze SLAs; the Gold promise includes maintenance without downtime (FR-015, FR-024).
- Q: How does the presenter fix Northbank live? → A: By hand in the Infrahub UI, moving the second path's gateway to `rb02-par01` within the failing branch. No automated repair in V1 (FR-018a).
