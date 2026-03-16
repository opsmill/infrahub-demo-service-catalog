# Quickstart: Semaphore UI Ansible Simulation

## Prerequisites

- Docker and Docker Compose installed
- The repository cloned locally
- No other services occupying ports 8000, 8501, or 3000

## Start the Stack

```bash
invoke start
```

This brings up Infrahub, the Streamlit service catalog, Semaphore UI, and all supporting services. Wait until all services are healthy (approximately 3-5 minutes on first run).

## Verify Services

| Service          | URL                    | Purpose                        |
|------------------|------------------------|--------------------------------|
| Infrahub         | http://localhost:8000  | Source of truth                 |
| Service Catalog  | http://localhost:8501  | Streamlit portal                |
| Semaphore UI     | http://localhost:3000  | Ansible automation interface    |

## Run a Deployment Simulation

1. **Open Semaphore UI** at http://localhost:3000
2. **Log in** with the default credentials (admin / changeme)
3. Navigate to the **"Service Catalog Deployment"** project
4. Click on **Task Templates** → **"Deploy Configuration"**
5. Click **Run** to trigger the playbook
6. Watch the task output — you should see per-device configuration deployment logs

## Full Demo Workflow

1. Open the **Service Catalog** (http://localhost:8501)
2. Request a new Dedicated Internet service
3. In **Infrahub** (http://localhost:8000), review and merge the proposed change
4. Open **Semaphore UI** (http://localhost:3000)
5. Run the **"Deploy Configuration"** task template
6. Observe the playbook fetching inventory from Infrahub and simulating configuration pushes to each device

## Teardown

```bash
invoke stop      # Stop containers
invoke destroy   # Stop and remove volumes
```
