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

3. To stop:

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

### Code Quality

- `invoke format` - Format code with ruff
- `invoke lint` - Run all linters (yamllint, ruff, mypy)
- `invoke lint-ruff` - Check code with ruff
- `invoke lint-mypy` - Type check with mypy
- `invoke lint-yaml` - Lint YAML files

### Testing

- `uv run pytest` - Run all tests
- `uv run pytest tests/unit/` - Run unit tests only
- `uv run pytest tests/integration/` - Run integration tests
- `uv run pytest -k test_name` - Run specific test

### Documentation

- `invoke docs` - Build documentation (requires npm in docs/ directory)
- `markdownlint docs/docs/**/*.mdx` - Lint documentation files
