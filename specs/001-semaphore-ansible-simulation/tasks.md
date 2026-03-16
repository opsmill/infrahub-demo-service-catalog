# Tasks: Semaphore UI Ansible Simulation

**Input**: Design documents from `/specs/001-semaphore-ansible-simulation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/semaphore-seed-api.md

**Tests**: Not explicitly requested in the feature specification. Test tasks are omitted.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the directory structure and foundational files for Ansible and Semaphore components

- [x] T001 Create Ansible directory structure: `ansible/`, `ansible/inventory/`, `ansible/roles/simulate_deploy/tasks/`
- [x] T002 [P] Create Ansible collection requirements in `ansible/collections/requirements.yml` declaring `opsmill.infrahub` dependency
- [x] T003 [P] Create Ansible configuration in `ansible/ansible.cfg` enabling the `opsmill.infrahub` inventory plugin
- [x] T004 Create Semaphore directory structure: `semaphore/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Docker Compose services and Semaphore image that ALL user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Create custom Semaphore Dockerfile in `semaphore/Dockerfile` that installs `opsmill.infrahub` Ansible collection and `infrahub-sdk` into the Semaphore image
- [x] T006 Add `semaphore-db` PostgreSQL service to `docker-compose.override.yml` with health check, using `postgres:16-alpine` image
- [x] T007 Add `semaphore` service to `docker-compose.override.yml` using the custom Dockerfile, exposing port 3000, with environment variables (`SEMAPHORE_DB_*`, `SEMAPHORE_ADMIN*`, `SEMAPHORE_FORWARDED_ENV_VARS` for `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN`), depending on `semaphore-db` and `infrahub-server` health checks
- [x] T008 Create the Infrahub dynamic inventory plugin configuration in `ansible/inventory/infrahub_inv.yml` pointing to `http://infrahub-server:8000` using `opsmill.infrahub.inventory` plugin with `DcimDevice` nodes

**Checkpoint**: Docker Compose stack starts with Semaphore UI accessible at http://localhost:3000 alongside Infrahub. Ansible artifacts are in place.

---

## Phase 3: User Story 1 - Launch Configuration Deployment Simulation (Priority: P1) MVP

**Goal**: An operator can run the deployment playbook in Semaphore UI, which fetches inventory from Infrahub and simulates configuration pushes to each device with per-device output.

**Independent Test**: Start Docker Compose, create and merge a proposed change in Infrahub, run the deployment playbook in Semaphore UI, and observe successful completion with per-device output in the logs.

### Implementation for User Story 1

- [x] T009 [P] [US1] Create the `simulate_deploy` role task file in `ansible/roles/simulate_deploy/tasks/main.yml` that fetches device configuration from Infrahub via `opsmill.infrahub.artifact_fetch` and outputs a simulated configuration push result per device
- [x] T010 [P] [US1] Create the deployment playbook in `ansible/deploy.yml` that targets all inventory hosts with `connection: local`, includes the `simulate_deploy` role, and produces per-device success/failure output
- [x] T011 [US1] Create the Semaphore init script in `semaphore/init-semaphore.sh` that waits for Semaphore to be healthy, authenticates via `POST /api/auth/login`, then seeds project, key store, repository (local path `/opt/semaphore/playbooks`), inventory, and task template via the Semaphore REST API per `contracts/semaphore-seed-api.md`
- [x] T012 [US1] Add `semaphore-init` service to `docker-compose.override.yml` as a one-shot init container that runs `semaphore/init-semaphore.sh`, depends on `semaphore` being healthy, and mounts the `ansible/` directory to `/opt/semaphore/playbooks`

**Checkpoint**: User Story 1 is fully functional. Operator can open Semaphore UI, find the pre-configured "Deploy Configuration" template, run it, and see per-device deployment simulation output.

---

## Phase 4: User Story 2 - Docker Compose One-Command Startup (Priority: P2)

**Goal**: A developer runs `invoke start` and Semaphore UI is accessible and fully pre-configured with no manual setup required.

**Independent Test**: From a clean state (no running containers), run `invoke start` and verify Semaphore UI is accessible at port 3000 with the project, inventory, and playbook already configured.

### Implementation for User Story 2

- [x] T013 [US2] Add Docker Compose health check to the `semaphore` service in `docker-compose.override.yml` (e.g., `curl -f http://localhost:3000/api/ping`) so downstream services and the init container can reliably depend on Semaphore readiness
- [x] T014 [US2] Ensure `semaphore-init` service in `docker-compose.override.yml` exits cleanly (exit code 0) on success and uses `restart: "no"` to avoid restart loops
- [x] T015 [US2] Add idempotency to `semaphore/init-semaphore.sh`: check if project already exists before creating, implement retry with exponential backoff (up to 60s) for connection errors per contract error handling requirements
- [x] T016 [US2] Verify that `invoke start` and `invoke stop` correctly manage all new services (semaphore, semaphore-db, semaphore-init) — update `tasks.py` if the invoke commands need adjustments to pick up `docker-compose.override.yml`

**Checkpoint**: `invoke start` from a clean state brings up the full stack. Semaphore UI is accessible and pre-configured within 5 minutes.

---

## Phase 5: User Story 3 - Simulated Device Feedback (Priority: P3)

**Goal**: Playbook output includes realistic network-device-style feedback (configuration diffs, hostname acknowledgment, simulated commit confirmations) instead of generic "ok" messages.

**Independent Test**: Run the deployment playbook and inspect per-device task output for realistic network-device-style messages.

### Implementation for User Story 3

- [x] T017 [US3] Enhance `ansible/roles/simulate_deploy/tasks/main.yml` to output realistic device-style feedback: configuration diff display, device hostname acknowledgment, and simulated commit confirmation message per device
- [x] T018 [US3] Add edge case handling to `ansible/deploy.yml`: skip devices with no generated configuration (emit warning), and fail with clear error when Infrahub is unreachable

**Checkpoint**: Playbook output now shows realistic network device responses. Edge cases (missing config, unreachable Infrahub) are handled gracefully.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and documentation

- [x] T019 Validate the full demo workflow end-to-end per `quickstart.md`: start stack, create service in catalog, merge proposed change, run deployment playbook, view results
- [x] T020 [P] Verify all Docker Compose health checks enforce correct startup ordering (Infrahub before Semaphore, Semaphore before init container)
- [x] T021 [P] Validate that Semaphore environment variable forwarding (`SEMAPHORE_FORWARDED_ENV_VARS`) correctly passes `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` to Ansible processes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational (Phase 2)
- **User Story 2 (Phase 4)**: Depends on User Story 1 (Phase 3) — init script and services must exist before hardening startup
- **User Story 3 (Phase 5)**: Depends on User Story 1 (Phase 3) — playbook and role must exist before enhancing output
- **Polish (Phase 6)**: Depends on all user stories being complete

### Within Each User Story

- Ansible artifacts (roles, playbooks) before Docker Compose integration
- Init script before init container service definition
- Core implementation before edge case handling

### Parallel Opportunities

- T002 and T003 can run in parallel (different files, no dependencies)
- T009 and T010 can run in parallel (role vs playbook, different files)
- T019, T020, and T021 can run in parallel (independent validations)
- User Story 3 can start as soon as User Story 1 is complete, independent of User Story 2

---

## Parallel Example: User Story 1

```
# Launch role and playbook creation together:
Task: T009 "Create simulate_deploy role in ansible/roles/simulate_deploy/tasks/main.yml"
Task: T010 "Create deployment playbook in ansible/deploy.yml"

# Then sequentially:
Task: T011 "Create init script in semaphore/init-semaphore.sh" (needs T009, T010 for context)
Task: T012 "Add semaphore-init service to docker-compose.override.yml" (needs T011)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (directory structure, Ansible deps)
2. Complete Phase 2: Foundational (Dockerfile, Docker Compose services, inventory config)
3. Complete Phase 3: User Story 1 (playbook, init script, init container)
4. **STOP and VALIDATE**: Start stack, verify Semaphore is pre-configured, run deployment playbook, check per-device output
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational -> Stack starts with Semaphore accessible
2. Add User Story 1 -> Playbook runs with simulated output -> Deploy/Demo (MVP!)
3. Add User Story 2 -> Harden startup, ensure one-command experience -> Deploy/Demo
4. Add User Story 3 -> Realistic device feedback in output -> Deploy/Demo
5. Polish -> End-to-end validation, health check verification

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- All file paths are relative to repository root
- No test tasks generated (not requested in specification)
