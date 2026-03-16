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
   - `schemas/` - Infrahub schema definitions (DCIM, IPAM, services)
   - `protocols_*.py` - Type definitions for Infrahub objects
   - Initial data in `data/` - YAML fixtures for demo environment

## Key Patterns

- **Dependency Injection**: Uses `fast-depends` for managing Infrahub client instances
- **Resource Allocation**: Automated allocation from pools (VLANs, IP prefixes)
- **Service Lifecycle**: Services move through states (pending -> active) with associated resource provisioning
- **Type Safety**: Comprehensive type hints with mypy validation

## Environment Configuration

Required environment variable:

- `INFRAHUB_ADDRESS` - URL of the Infrahub instance

## Development Tips

- The application uses Streamlit's session state for managing UI state
- Infrahub client is cached using `@st.cache_resource` decorator
- All Infrahub operations should use the dependency-injected client from `infrahub.py`
- Service generators run asynchronously in Infrahub after service creation
