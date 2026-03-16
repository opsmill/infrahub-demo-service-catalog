<!--
Sync Impact Report
===================
Version change: 0.0.0 → 1.0.0 (initial ratification)
Modified principles: N/A (first version)
Added sections:
  - Core Principles (5): Infrahub-First, Type Safety, Test Discipline,
    Service Lifecycle Integrity, Simplicity & YAGNI
  - Technology Constraints
  - Development Workflow
  - Governance
Removed sections: None
Templates requiring updates:
  - .specify/templates/plan-template.md — ✅ no update needed
    (Constitution Check section already references this file dynamically)
  - .specify/templates/spec-template.md — ✅ no update needed
    (user stories and requirements sections align with principles)
  - .specify/templates/tasks-template.md — ✅ no update needed
    (phase structure compatible with principles)
Follow-up TODOs: None
-->

# Service Catalog Constitution

## Core Principles

### I. Infrahub-First

All data management and service orchestration MUST go through the
Infrahub SDK. Direct database access or bypassing the Infrahub API
is prohibited.

- Every data operation MUST use the dependency-injected Infrahub
  client from `service_catalog/infrahub.py`.
- Resource allocation (VLANs, IP prefixes, ports) MUST use Infrahub
  pool mechanisms — never manual ID assignment.
- Branch-based change management MUST be used for any operation that
  modifies shared state.
- GraphQL queries MUST be the sole interface for reading Infrahub data.

**Rationale**: Infrahub is the single source of truth. Bypassing it
creates data inconsistencies and breaks audit trails.

### II. Type Safety

All Python code MUST pass strict type checking with mypy. Type hints
are not optional.

- Every function MUST have complete type annotations (arguments and
  return types).
- Infrahub object types MUST be defined in `protocols_*.py` files
  and used consistently.
- `Any` type MUST NOT be used unless interfacing with an untyped
  third-party API, and such usage MUST be documented with a comment.
- mypy MUST run clean (`invoke lint-mypy`) before any code is
  considered complete.

**Rationale**: The Infrahub SDK relies heavily on typed protocols.
Type safety prevents runtime errors in service provisioning where
failures are costly to debug and reverse.

### III. Test Discipline

Code changes MUST be validated by tests. Unit tests are the baseline;
integration tests are required for Infrahub interactions.

- Unit tests MUST cover all business logic in generators and service
  implementations.
- Integration tests MUST validate Infrahub SDK interactions using
  `infrahub-testcontainers`.
- Tests MUST run with `uv run pytest` and pass before code is
  considered complete.
- Mocking Infrahub responses is acceptable for unit tests but MUST
  NOT replace integration tests for critical paths (resource
  allocation, service lifecycle transitions).

**Rationale**: Service provisioning allocates real network resources.
Untested code risks allocating duplicate VLANs, orphaning IP
prefixes, or leaving services in inconsistent states.

### IV. Service Lifecycle Integrity

Services MUST follow defined state transitions. No service may skip
states or transition without completing all prerequisite resource
allocations.

- Service state transitions (e.g., pending → active) MUST be
  explicitly managed through generators.
- Resource allocation (VLANs, IP prefixes, ports, gateways) MUST
  complete successfully before a service transitions to active.
- Failed allocations MUST leave the service in its previous state
  with clear error reporting — no partial transitions.
- Every new service type MUST define its complete lifecycle in a
  dedicated generator under `generators/`.

**Rationale**: Network resources are shared and finite. Partial
provisioning creates orphaned allocations that are difficult to
reclaim and can cause conflicts for subsequent requests.

### V. Simplicity & YAGNI

Start with the simplest solution that works. Do not add abstractions,
configuration options, or features ahead of demonstrated need.

- New code MUST solve a current, concrete requirement — not a
  hypothetical future one.
- Prefer inline logic over helper functions when the logic is used
  once.
- Streamlit pages MUST remain self-contained; avoid shared UI
  component libraries unless three or more pages share identical
  patterns.
- Dependencies MUST NOT be added without justification. The project
  uses a deliberate, minimal dependency set.

**Rationale**: This is a proof-of-concept / demo project. Over-
engineering obscures the patterns being demonstrated and increases
maintenance burden without delivering user value.

## Technology Constraints

- **Python**: >=3.10, <3.13
- **Package manager**: uv (all dependency operations via `uv sync`)
- **Core dependencies**: infrahub-sdk, streamlit, fast-depends
- **Linting**: ruff (format + lint), mypy, yamllint
- **Testing**: pytest, pytest-asyncio, infrahub-testcontainers
- **Containerization**: Docker + Docker Compose for full-stack runs
- **Environment**: `INFRAHUB_ADDRESS` MUST be set to target an
  Infrahub instance

Adding new runtime dependencies MUST be discussed and justified.
Dev dependencies may be added when they improve code quality tooling.

## Development Workflow

- **Formatting**: `invoke format` MUST be run before committing.
- **Linting**: `invoke lint` MUST pass (ruff, mypy, yamllint).
- **Testing**: `uv run pytest` MUST pass.
- **Branch strategy**: Feature work happens on branches; changes are
  merged via pull request.
- **Code review**: All PRs MUST be reviewed before merge.
- **Commit hygiene**: Commits MUST be atomic and describe the "why"
  not the "what".

Quality gates are enforced in this order: format → lint → test.
A failure at any gate MUST be resolved before proceeding.

## Governance

This constitution is the authoritative source for project-level
development principles. It supersedes ad-hoc conventions and
informal agreements.

- **Amendments**: Any principle change MUST be documented with a
  version bump, rationale, and updated Sync Impact Report.
- **Versioning**: Follows semantic versioning:
  - MAJOR: Principle removal or incompatible redefinition.
  - MINOR: New principle or material expansion of existing guidance.
  - PATCH: Clarifications, wording, or non-semantic refinements.
- **Compliance review**: All PRs SHOULD be checked against these
  principles. Reviewers MAY reference specific principle numbers
  (e.g., "violates Principle II") in review comments.
- **Dispute resolution**: When principles conflict with practical
  constraints, document the deviation in a Complexity Tracking table
  (see plan template) with justification.

**Version**: 1.0.0 | **Ratified**: 2026-03-16 | **Last Amended**: 2026-03-16
