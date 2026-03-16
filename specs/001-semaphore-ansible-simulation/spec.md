# Feature Specification: Semaphore UI Ansible Simulation

**Feature Branch**: `001-semaphore-ansible-simulation`
**Created**: 2026-03-16
**Status**: Draft
**Input**: User description: "Add a Semaphore UI component to run Ansible playbooks that simulate pushing updated configurations to network devices after a proposed change is merged. No actual network devices — the goal is a simulated environment. Semaphore UI must run in Docker Compose and be configured with the Ansible Inventory plugin to pull configuration from Infrahub."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Launch Configuration Deployment Simulation (Priority: P1)

A demo operator wants to see the end-to-end workflow of merging a proposed change in Infrahub and then deploying the resulting configuration to simulated network devices. After a proposed change is merged in Infrahub, the operator opens Semaphore UI, selects the deployment playbook, and runs it. Semaphore fetches the device inventory from Infrahub via the Ansible Inventory plugin, retrieves the generated device configurations, and executes the playbook against simulated targets. The operator sees the playbook run complete successfully with a log showing which devices received configuration updates.

**Why this priority**: This is the core value proposition — demonstrating automated config deployment triggered after a change is merged. Without this, there is no demo.

**Independent Test**: Can be fully tested by starting Docker Compose, creating and merging a proposed change in Infrahub, then running the deployment playbook in Semaphore UI and observing successful completion with device-level output in the logs.

**Acceptance Scenarios**:

1. **Given** Infrahub is running with devices and a merged proposed change, **When** the operator triggers the deployment playbook in Semaphore UI, **Then** the playbook completes successfully and logs show configuration was "pushed" to each target device.
2. **Given** Semaphore UI is running in Docker Compose, **When** the operator views the project configuration, **Then** the Infrahub-sourced inventory is visible and lists the correct devices and their attributes.
3. **Given** a playbook run has completed, **When** the operator reviews the task output in Semaphore UI, **Then** per-device status (success/failure) and configuration details are visible.

---

### User Story 2 - Docker Compose One-Command Startup (Priority: P2)

A developer or demo presenter wants to bring up the entire stack — Infrahub, Streamlit service catalog, and Semaphore UI with its dependencies — using a single `invoke start` command. Semaphore UI and its backing database start alongside the existing services, and Semaphore is pre-configured with the correct project, inventory source, and playbook repository so that no manual setup is required after startup.

**Why this priority**: A frictionless demo experience is essential. If Semaphore requires manual post-startup configuration, the demo loses impact and reproducibility.

**Independent Test**: Can be tested by running `invoke start` from a clean state and verifying that Semaphore UI is accessible and pre-configured without any manual intervention.

**Acceptance Scenarios**:

1. **Given** a clean environment with no running containers, **When** the developer runs `invoke start`, **Then** Semaphore UI is accessible at its designated port and all required services are healthy.
2. **Given** the stack is running, **When** the developer navigates to Semaphore UI, **Then** the project, inventory, and playbook are already configured and ready to use.

---

### User Story 3 - Simulated Device Feedback (Priority: P3)

A demo presenter wants to show realistic output from the simulated network devices during the playbook run. Instead of generic "ok" messages, the simulation produces output that resembles what a real network device would return when receiving a configuration push (for example, showing the configuration diff applied, device hostname acknowledgment, or a simulated commit confirmation).

**Why this priority**: This enhances the demo realism but is not required for the core workflow to function. The simulation works with basic output; realistic feedback is a polish item.

**Independent Test**: Can be tested by running the deployment playbook and inspecting the per-device task output for realistic network-device-style messages.

**Acceptance Scenarios**:

1. **Given** the deployment playbook runs against simulated devices, **When** the operator inspects task output for a device, **Then** the output includes device-style feedback (configuration diff, hostname, confirmation message).

---

### Edge Cases

- What happens when Infrahub is unreachable from Semaphore at playbook runtime? The playbook MUST fail with a clear error indicating the inventory source is unavailable.
- What happens when a device listed in the inventory has no generated configuration? The playbook MUST skip that device with a warning rather than failing the entire run.
- What happens when Semaphore UI starts before Infrahub is fully healthy? Semaphore MUST retry or wait gracefully; Docker Compose health checks MUST enforce startup ordering.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST include Semaphore UI as a service in Docker Compose, starting alongside existing Infrahub and Streamlit services.
- **FR-002**: Semaphore UI MUST be pre-configured with a project that uses the Infrahub Ansible Inventory plugin as its inventory source.
- **FR-003**: The Ansible Inventory plugin MUST connect to the Infrahub instance running in Docker Compose to retrieve the device inventory dynamically.
- **FR-004**: The system MUST include at least one Ansible playbook that retrieves device configurations from Infrahub and simulates pushing them to target devices.
- **FR-005**: The playbook MUST target simulated devices (no real network equipment required) and produce per-device output indicating success or failure.
- **FR-006**: Semaphore UI MUST be accessible via a browser on a designated port without requiring authentication for the demo environment.
- **FR-007**: The Semaphore UI project MUST be pre-configured at startup (project, inventory, playbook repository) so no manual setup is needed after `invoke start`.
- **FR-008**: The system MUST include a Semaphore backing database in Docker Compose for persisting Semaphore project and task history.
- **FR-009**: Docker Compose health checks MUST ensure Semaphore starts only after Infrahub is healthy and reachable.

### Key Entities

- **Semaphore Project**: The configured project in Semaphore UI linking the inventory source and playbook repository.
- **Ansible Inventory (Infrahub plugin)**: Dynamic inventory sourced from Infrahub, providing device hostnames, roles, locations, and attributes.
- **Deployment Playbook**: An Ansible playbook that fetches generated configurations from Infrahub and applies them to simulated targets.
- **Simulated Device Target**: A lightweight simulation target (for example, localhost with a role-based mock) that accepts configuration pushes and produces realistic output.

### Assumptions

- Semaphore UI supports pre-configuration via environment variables, seed data, or an initialization script at container startup.
- The Infrahub Ansible Inventory plugin is publicly available and compatible with the Infrahub SDK version used in this project (>=1.17.0).
- Simulated devices will run as localhost tasks or containerized mock endpoints within the Docker Compose stack — no external infrastructure is required.
- The playbook retrieves configuration artifacts that are already generated and stored in Infrahub (for example, via Jinja2 transforms or generators); the playbook does not generate configurations itself.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The entire stack (Infrahub + Streamlit + Semaphore UI) starts with a single command and all services are healthy within 5 minutes.
- **SC-002**: A first-time user can trigger a deployment simulation in Semaphore UI within 2 minutes of the stack becoming healthy, without any manual configuration steps.
- **SC-003**: The deployment playbook completes against all inventory devices and produces per-device output within 3 minutes of being triggered.
- **SC-004**: 100% of devices in the Infrahub inventory appear in the Semaphore inventory view.
- **SC-005**: A demo presenter can walk through the full workflow (create service in catalog, merge proposed change, run deployment playbook, view results) in under 10 minutes.
