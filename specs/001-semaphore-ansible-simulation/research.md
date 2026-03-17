# Research: Semaphore UI Ansible Simulation

## R-001: Semaphore UI Docker Deployment

**Decision**: Use `semaphoreui/semaphore:latest` Docker image with PostgreSQL backend.

**Rationale**: PostgreSQL is already a pattern in this stack (task-manager-db uses postgres:16-alpine). SQLite is simpler but PostgreSQL aligns with the existing infrastructure and supports concurrent access better. The image listens on port 3000 by default.

**Alternatives considered**:

- SQLite: Simpler but less aligned with existing stack patterns. No separate DB container needed, but harder to debug/inspect.
- MySQL: Supported but would add a new database engine to the stack unnecessarily.
- BoltDB: Deprecated as of v2.16, will be removed in v3.0.

## R-002: Semaphore Pre-Configuration (Seeding)

**Decision**: Use an init container (or entrypoint wrapper script) that waits for Semaphore to be healthy, then calls the Semaphore REST API to create the project, repository, inventory, and task template.

**Rationale**: Semaphore does not support config-file-based seeding. The REST API is comprehensive and well-documented. An init container pattern is clean, idempotent, and keeps the Semaphore container unmodified. Key API endpoints:

- `POST /api/auth/login` — authenticate and get token
- `POST /api/projects` — create project
- `POST /api/project/{id}/repositories` — add playbook repository
- `POST /api/project/{id}/inventory` — add inventory
- `POST /api/project/{id}/templates` — add task template (playbook)

**Alternatives considered**:

- Manual setup after startup: Violates FR-007 (no manual setup).
- Mounting a pre-built SQLite/PostgreSQL database: Fragile, version-dependent, hard to maintain.

## R-003: Infrahub Ansible Inventory Plugin

**Decision**: Use the `opsmill.infrahub` Ansible collection (`opsmill.infrahub.inventory` plugin) for dynamic inventory sourced from Infrahub.

**Rationale**: This is the official, maintained collection by OpsMill (the Infrahub authors). It supports:

- Dynamic inventory via `opsmill.infrahub.inventory` plugin
- Artifact fetching via `opsmill.infrahub.artifact_fetch` module
- GraphQL queries via `opsmill.infrahub.query_graphql` action plugin
- Authentication via `INFRAHUB_API_TOKEN` and `INFRAHUB_ADDRESS` environment variables

Requirements: Python 3.10-3.12, Ansible 2.16+, infrahub-sdk >= 1.5.0.

**Alternatives considered**:

- Custom inventory script: Unnecessary when official plugin exists.
- Static inventory: Would not demonstrate the dynamic Infrahub integration.

## R-004: Inventory Configuration

**Decision**: Create an inventory YAML file using `opsmill.infrahub.inventory` plugin pointing to the Infrahub instance within Docker Compose.

**Rationale**: The inventory file format is:

```yaml
plugin: opsmill.infrahub.inventory
api_endpoint: http://infrahub-server:8000
token: <INFRAHUB_API_TOKEN>
nodes:
  - kind: DcimDevice
    attributes:
      - name
      - role
      - status
      - platform
```

This aligns with FR-003 (dynamic inventory from Infrahub) and uses the internal Docker network for communication.

## R-005: Simulation Approach

**Decision**: Run playbooks against `localhost` using `connection: local` with custom Ansible modules or debug tasks that simulate device configuration push. The Semaphore container itself acts as the "simulated device" target.

**Rationale**: No real network devices are available (per spec). Running against localhost with `connection: local` is the simplest approach. The playbook will:

1. Fetch device inventory from Infrahub (via inventory plugin)
2. Fetch generated configuration artifacts from Infrahub (via `opsmill.infrahub.artifact_fetch`)
3. Simulate a configuration push by printing the config diff and a simulated commit message

This satisfies FR-005 (simulated devices, per-device output) without requiring additional containers or mock network devices.

**Alternatives considered**:

- Containerized mock devices (e.g., fake SSH endpoints): Over-engineered for a demo, adds complexity without meaningful value.
- Network simulation tools (GNS3, Containerlab): Heavy dependencies, violates Principle V (Simplicity & YAGNI).

## R-006: Playbook Repository Location

**Decision**: Use a local filesystem path within the Semaphore container, mounting the playbook directory from the project repository.

**Rationale**: Semaphore supports local path repositories (`/path/to/repo`). Mounting the playbook directory via Docker volume is simpler than configuring Git access from within the Semaphore container. This keeps all playbook files in the project repository where they can be version-controlled alongside the rest of the code.

**Alternatives considered**:

- Git URL pointing to the same repo: Would require SSH key or token management within Semaphore for a private repo. Adds unnecessary complexity for a local demo.

## R-007: Semaphore Authentication for Demo

**Decision**: Configure Semaphore with a default admin user via environment variables. No additional authentication hardening needed.

**Rationale**: FR-006 specifies the demo does not require authentication. Semaphore requires at least one admin user, which is created via `SEMAPHORE_ADMIN`, `SEMAPHORE_ADMIN_PASSWORD`, `SEMAPHORE_ADMIN_NAME`, and `SEMAPHORE_ADMIN_EMAIL` environment variables. The init script will use these credentials to authenticate with the API.

## R-008: Environment Variable Forwarding

**Decision**: Use `SEMAPHORE_FORWARDED_ENV_VARS` to pass `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` from the Semaphore container environment to Ansible task processes.

**Rationale**: The Ansible inventory plugin and artifact_fetch module need to reach Infrahub. Semaphore's `SEMAPHORE_FORWARDED_ENV_VARS` mechanism forwards specified environment variables to spawned Ansible processes, which is cleaner than hardcoding values in playbook vars.
