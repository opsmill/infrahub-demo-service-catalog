# Architecture Overview

## Core Components

1. **Streamlit Portal** (`service_catalog/`)
   - Entry point: `portal.py` - Builds the sidebar with `st.navigation` from `navigation.py`: a "Service catalog" section (Home, Service Requests, Dedicated Internet, Wireless) and a "Business impact" section (Planned maintenance, Single points of failure, Customer notification, Cost of service). Each page has its own `url_path`. The page files are in `views/`, not `pages/`, because Streamlit treats a `pages/` folder next to the entry point as old-style folder pages and shows "Page not found" for the first link opened after a restart. A new page must be added to `navigation.py`
   - Home page: `🏠_Home_Page.py` - Cards that open the other pages
   - Service pages in `views/` - Individual service request forms and the business impact pages
   - `infrahub.py` - Infrahub SDK client wrapper with caching and dependency injection
   - `views/3_📊_Planned_Maintenance.py` and `views/6_📍_Single_Points_of_Failure.py` - Read-only pages for the business impact demo, from the stored query `queries/business_impact_services.gql`. Planned maintenance: services with fewer separate paths during a selected proposed change, and their customers. Single points of failure: on main, the Gold services that depend on a single device and what would have no path if a selected device failed now. Both pages render through `business_impact/page_views.py`
   - `business_impact/` - Pure functions behind the pages (`blast_radius.py`, `single_points.py`), the Streamlit reads and rendering both pages share (`page_views.py`), the guard run the check and the transforms share (`change_impact.py`) and the `invoke seed` steps (`seed.py`)
   - `business_impact/footprint.py` - The one way the demo finds a service's paths: Infrahub path traversal (`traverse_paths`) from each active service to the switches and edge routers at its site (two relationships deep) and, when the circuit schema is loaded, to the upstream circuits at its site (five relationships deep). `with_footprints` adds the result to a query result, where the Gold outage guard, the business impact pages, the transforms and `cost_of_service/` read each service's devices and circuits
   - `network.py` - Readers for stored query results and the rule that pairs a switch and the edge router of the same index at the same site into a path, shared by `business_impact/` and `cost_of_service/`

2. **Infrahub Integration**
   - Uses Infrahub SDK for data management and service orchestration
   - GraphQL-based API communication
   - Branch-based change management support

3. **Service Implementation**
   - `generators/` - Infrahub generators for automated service provisioning
   - `checks/gold_outage_guard.py` - Proposed change check that fails, and so blocks the merge, when a change leaves an active service with fewer separate paths than its tier's `min_paths` rule, or raises a tier's rule that active services do not meet; it runs the `business_impact_services` query and `service_catalog/business_impact/change_impact.py`, which adds the footprints on the branch and on main, as the two notification transforms do
   - Example: `implement_dedicated_internet.py` allocates VLANs, IP prefixes, ports, and configures gateways

4. **Data Models**
   - `schemas/` - Infrahub schema definitions (DCIM, IPAM, services, and the optional circuit schema, commented out in `.infrahub.yml` and loaded by `invoke seed`)
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
- **Business Impact Demo Seed**: `invoke seed` runs after `invoke init`. It describes the repository items in Infrahub, loads the circuit schema (optional in `.infrahub.yml`) and the upstream circuits of `data/business_impact/upstream_circuits.yml`, creates twelve services on `main`, runs the generator for each one, gives the three Paris Gold services a second path, and opens three maintenance proposed changes (Paris router 1, which the Gold outage guard passes; Brussels switch 1, which it blocks; New York router 1, which it passes). The Planned maintenance and Customer notification pages and the Gold outage guard check read those changes; the Single points of failure and Cost of service pages read the services on `main`

## Environment Configuration

Required environment variable:

- `INFRAHUB_ADDRESS` - URL of the Infrahub instance

## Development Tips

- The application uses Streamlit's session state for managing UI state
- Infrahub client is cached using `@st.cache_resource` decorator
- All Infrahub operations should use the dependency-injected client from `infrahub.py`
- Service generators run asynchronously in Infrahub after service creation
- Semaphore mounts the `ansible/` directory as its playbook source; changes to playbooks are reflected immediately
