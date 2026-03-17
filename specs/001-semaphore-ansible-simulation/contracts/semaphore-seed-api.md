# Contract: Semaphore Seed API Calls

The init container (or script) MUST call the following Semaphore REST API
endpoints in order to pre-configure the project at startup.

## Authentication

```text
POST /api/auth/login
Content-Type: application/json

{
  "auth": "<SEMAPHORE_ADMIN>",
  "password": "<SEMAPHORE_ADMIN_PASSWORD>"
}

Response: { "token": "<bearer_token>" }
```

All subsequent calls use `Authorization: Bearer <bearer_token>`.

## 1. Create Project

```text
POST /api/projects
{
  "name": "Service Catalog Deployment",
  "alert": false,
  "max_parallel_tasks": 0
}

Response: { "id": 1, "name": "Service Catalog Deployment", ... }
```

## 2. Create Key Store Entry

```text
POST /api/project/1/keys
{
  "name": "Local Access",
  "type": "none",
  "project_id": 1
}

Response: { "id": 1, ... }
```

## 3. Create Repository

```text
POST /api/project/1/repositories
{
  "name": "Local Playbooks",
  "project_id": 1,
  "git_url": "/opt/semaphore/playbooks",
  "git_branch": "",
  "ssh_key_id": 1
}

Response: { "id": 1, ... }
```

## 4. Create Inventory

```text
POST /api/project/1/inventory
{
  "name": "Infrahub Devices",
  "project_id": 1,
  "inventory": "/opt/semaphore/playbooks/inventory/infrahub_inv.yml",
  "type": "file",
  "ssh_key_id": 1
}

Response: { "id": 1, ... }
```

## 5. Create Task Template

```text
POST /api/project/1/templates
{
  "name": "Deploy Configuration",
  "project_id": 1,
  "repository_id": 1,
  "inventory_id": 1,
  "playbook": "deploy.yml",
  "type": "task"
}

Response: { "id": 1, ... }
```

## Error Handling

- The init script MUST be idempotent: if the project already exists, skip creation.
- The init script MUST retry on connection errors (Semaphore not yet healthy) with exponential backoff up to 60 seconds.
- The init script MUST exit with code 0 on success to avoid Docker Compose restart loops.
