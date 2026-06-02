# Architecture Overview

## Core Components

1. **Streamlit Portal** (`service_catalog/`)
   - Entry point: `🏠_Home_Page.py` - Main portal interface
   - Service pages in `pages/` - Individual service request forms
   - `infrahub.py` - Infrahub SDK client wrapper with caching and dependency injection

2. **Infrahub Integration**
   - Uses Infrahub SDK for data management and service orchestration
   - GraphQL-based API communication
   - Branch-based change management support

3. **Service Implementation**
   - `generators/` - Infrahub generators for automated service provisioning
   - Example: `implement_dedicated_internet.py` allocates VLANs, IP prefixes, ports, and configures gateways

4. **Data Models**
   - `schemas/` - Infrahub schema definitions (DCIM, IPAM, services, and optional circuit schema)
   - `protocols_*.py` - Type definitions for Infrahub objects
   - Initial data in `data/` - YAML fixtures for demo environment (locations, devices, providers, profiles, resource pools)
   - `bootstrap/permissions.yml` - RBAC configuration (operator role/group, `john` user account)
   - `bootstrap/repository.yaml` - `CoreRepository` definition loaded by `invoke init`
   - `menu.yml` - Custom Infrahub menu structure for locations, devices, and services

5. **Semaphore (Ansible Automation)** (`ansible/`, `semaphore/`)
   - Open-source web UI (SemaphoreUI) for running Ansible playbooks
   - `ansible/deploy.yml` - Fetches startup-config artifacts from Infrahub and saves them locally
   - `ansible/inventory.yml` - Dynamic inventory using `opsmill.infrahub.inventory` plugin
   - `semaphore/Dockerfile` - Custom image with infrahub-sdk and opsmill.infrahub Ansible collection
   - Accessible at http://localhost:3000 (admin / semaphore)

## Key Patterns

- **Dependency Injection**: Uses `fast-depends` for managing Infrahub client instances
- **Resource Allocation**: Automated allocation from pools (VLANs, IP prefixes)
- **Service Lifecycle**: Services move through states (pending -> active) with associated resource provisioning
- **Type Safety**: Comprehensive type hints with mypy validation
- **Configuration Deployment**: Semaphore runs Ansible playbooks that pull generated artifacts from Infrahub and deploy them to devices
- **Demo Initialization**: `invoke init` seeds Semaphore and loads repository configuration + permissions into Infrahub

## Environment Configuration

Required environment variable:

- `INFRAHUB_ADDRESS` - URL of the Infrahub instance

## Development Tips

- The application uses Streamlit's session state for managing UI state
- Infrahub client is cached using `@st.cache_resource` decorator
- All Infrahub operations should use the dependency-injected client from `infrahub.py`
- Service generators run asynchronously in Infrahub after service creation
- Semaphore mounts the `ansible/` directory as its playbook source; changes to playbooks are reflected immediately
