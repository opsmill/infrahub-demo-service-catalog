# Getting Started

## Prerequisites

- Python >=3.10, <3.13
- [uv](https://docs.astral.sh/uv/) package manager
- Docker and Docker Compose (for running the full stack)
- An Infrahub instance (set `INFRAHUB_ADDRESS` environment variable)

## Setup

1. Install dependencies:

   ```bash
   uv sync
   ```

2. Start the application with Docker Compose:

   ```bash
   invoke start
   ```

3. Initialize the demo (seeds Semaphore, loads repository and permissions):

   ```bash
   invoke init
   ```

4. To stop:

   ```bash
   invoke stop
   ```

## Common Development Commands

### Docker Operations

- `invoke build` - Build Docker containers
- `invoke start` - Start the application with Docker Compose
- `invoke stop` - Stop Docker containers
- `invoke destroy` - Stop and remove volumes
- `invoke restart` - Restart containers
- `invoke init` - Initialize demo (seed Semaphore, load repository and permissions)
- `invoke init-semaphore` - Seed Semaphore only (project, keys, inventory, task template)

### Code Quality

- `invoke format` - Format code with ruff
- `invoke lint` - Run all linters (yamllint, ruff, mypy)
- `invoke lint-ruff` - Check code with ruff
- `invoke lint-mypy` - Type check with mypy
- `invoke lint-yaml` - Lint YAML files

### Testing

- `invoke test` - Run the full test suite (unit and integration)
- `invoke test-unit` - Run unit tests only (no Docker required)
- `invoke test-integration` - Run integration tests (spins up a Dockerized Infrahub instance via `infrahub-testcontainers`)
- `uv run pytest -k test_name` - Run a specific test

### Documentation

- `invoke docs` - Build documentation (requires npm in docs/ directory)
- `rumdl check docs/docs/**/*.mdx` - Lint documentation files
