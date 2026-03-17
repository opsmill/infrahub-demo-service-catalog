# Data Model: Semaphore UI Ansible Simulation

This feature does not introduce new Infrahub schema entities. It adds infrastructure components (Docker services) and configuration files. The "data model" here describes the Semaphore-side entities that must be seeded at startup.

## Semaphore Entities (Seeded via API)

### Project

- **Name**: "Service Catalog Deployment"
- **Purpose**: Groups the inventory, repository, and task templates for the deployment simulation.

### Key Store Entry

- **Name**: "Infrahub API Token" (or "None" key for local repo access)
- **Type**: Login/password or empty (for local filesystem repository)
- **Purpose**: Stores credentials used by Semaphore to access the playbook repository and by Ansible to access Infrahub.

### Repository

- **Name**: "Local Playbooks"
- **URL**: Local filesystem path (e.g., `/opt/semaphore/playbooks`)
- **Branch**: N/A (local path)
- **Purpose**: Points Semaphore to the mounted playbook directory containing the deployment playbook and inventory configuration.

### Inventory

- **Name**: "Infrahub Devices"
- **Type**: File-based (references the `opsmill.infrahub.inventory` plugin config file within the mounted playbook directory)
- **Purpose**: Dynamic inventory sourced from Infrahub via the inventory plugin.

### Task Template

- **Name**: "Deploy Configuration"
- **Playbook**: Path to the deployment playbook within the repository (e.g., `deploy.yml`)
- **Inventory**: References the "Infrahub Devices" inventory
- **Purpose**: The runnable task that operators trigger in Semaphore UI to simulate configuration deployment.

## Ansible Artifacts (Files in Repository)

### Inventory Plugin Configuration (`inventory/infrahub_inv.yml`)

```yaml
plugin: opsmill.infrahub.inventory
api_endpoint: "{{ lookup('env', 'INFRAHUB_ADDRESS') }}"
token: "{{ lookup('env', 'INFRAHUB_API_TOKEN') }}"
nodes:
  - kind: DcimDevice
    attributes:
      - name
      - role
      - status
      - platform
```

### Deployment Playbook (`deploy.yml`)

High-level structure:

1. Gather inventory from Infrahub (automatic via inventory plugin)
2. For each device, fetch generated configuration artifact from Infrahub
3. Simulate configuration push (print config, emit simulated device response)
4. Report per-device success/failure

## Relationships

```text
Semaphore Project
├── Key Store Entry (credentials)
├── Repository (local playbook path)
├── Inventory (Infrahub dynamic inventory)
└── Task Template (deploy playbook)
       ├── uses → Repository
       └── uses → Inventory
```

## State Transitions

No state transitions are introduced by this feature. Semaphore task runs have built-in states (waiting, running, success, error) managed by Semaphore itself.
