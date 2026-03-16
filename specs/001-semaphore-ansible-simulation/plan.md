# Implementation Plan: Semaphore UI Ansible Simulation

**Branch**: `001-semaphore-ansible-simulation` | **Date**: 2026-03-16 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-semaphore-ansible-simulation/spec.md`

## Summary

Add Semaphore UI to the Docker Compose stack to demonstrate Ansible-based configuration deployment after a proposed change is merged in Infrahub. Semaphore fetches device inventory dynamically from Infrahub via the `opsmill.infrahub` Ansible collection and runs a deployment playbook against simulated (localhost) targets. An init container seeds Semaphore with the project, inventory, repository, and task template via the REST API so no manual setup is needed.

## Technical Context

**Language/Version**: Python >=3.10, <3.13 (for init script); YAML/Ansible for playbooks
**Primary Dependencies**: Semaphore UI (Docker image `semaphoreui/semaphore`), `opsmill.infrahub` Ansible collection, `infrahub-sdk`
**Storage**: PostgreSQL (Semaphore backing database, new container)
**Testing**: Manual validation via Docker Compose stack; existing `uv run pytest` for any Python init scripts
**Target Platform**: Docker Compose (Linux containers)
**Project Type**: Infrastructure/configuration addition to existing Docker Compose stack
**Performance Goals**: Stack healthy within 5 minutes; playbook completes within 3 minutes
**Constraints**: No real network devices; all simulation on localhost
**Scale/Scope**: Single Semaphore project, single playbook, inventory of existing demo devices (~4-8 devices)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Infrahub-First | PASS | Inventory sourced from Infrahub via official plugin. Configuration artifacts fetched from Infrahub. No direct database access. |
| II. Type Safety | PASS | Minimal new Python code (init script only). Any Python MUST have type annotations. Playbooks are YAML — type safety N/A. |
| III. Test Discipline | PASS | Init script logic testable via unit tests. Docker Compose integration validated manually (consistent with existing stack testing). |
| IV. Service Lifecycle Integrity | N/A | This feature does not introduce new service types or state transitions. It operates downstream of the existing lifecycle. |
| V. Simplicity & YAGNI | PASS | Using localhost simulation instead of mock device containers. Local repo mount instead of Git URL. PostgreSQL reuses existing pattern. Init container is the minimum needed for pre-configuration. |

**Post-Design Re-Check**: All gates still pass. No new violations introduced.

## Project Structure

### Documentation (this feature)

```text
specs/001-semaphore-ansible-simulation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── semaphore-seed-api.md
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
ansible/
├── deploy.yml                    # Main deployment playbook
├── ansible.cfg                   # Ansible configuration
├── inventory/
│   └── infrahub_inv.yml          # Infrahub dynamic inventory plugin config
├── roles/
│   └── simulate_deploy/
│       └── tasks/
│           └── main.yml          # Simulated config push tasks
└── collections/
    └── requirements.yml          # opsmill.infrahub collection dependency

semaphore/
├── init-semaphore.sh             # Init script to seed Semaphore via API
└── Dockerfile                    # Custom Semaphore image with Ansible deps

docker-compose.override.yml      # Updated: add semaphore + semaphore-db + semaphore-init services
```

**Structure Decision**: Infrastructure-as-configuration pattern. New `ansible/` directory at repo root for all Ansible artifacts. New `semaphore/` directory for Semaphore-specific Docker build and init script. Docker Compose override file extended with new services. No changes to existing `service_catalog/` or `generators/` code.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| New PostgreSQL container for Semaphore | Semaphore requires a database backend | SQLite would work but PostgreSQL aligns with existing stack pattern (task-manager-db). Consistent operations. |
| Init container for seeding | Semaphore has no config-file seeding | Manual setup violates FR-007. Database pre-seeding is fragile across versions. API seeding is the officially supported approach. |
| Custom Semaphore Dockerfile | Need to install `opsmill.infrahub` collection and `infrahub-sdk` into the Semaphore image | Using the stock image would require post-startup installation on every restart, which is slower and fragile. |
