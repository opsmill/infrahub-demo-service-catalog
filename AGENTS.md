# AGENTS.md

This file provides guidance to AI coding assistants working with this repository.

## Repository Overview

This is a Service Catalog demo built with Infrahub and Streamlit that allows users to request and manage network services through a web portal. The application demonstrates how to build a service factory on top of a source of truth system, with automated resource allocation (VLANs, IP prefixes, ports) and service lifecycle management.

## Project Structure

@dev/knowledges/architecture.md

## Getting Started

@dev/guides/getting-started.md

## Development Guides

@dev/guides/

## Development Guidelines

@dev/guidelines/

## Domain Knowledge

@dev/knowledges/

## Custom Commands

@dev/commands/

## Quick Reference

### Install Dependencies

```bash
uv sync
```

### Format Code

```bash
invoke format
```

### Run Linting

```bash
invoke lint
```

### Run Tests

```bash
uv run invoke test                          # unit + integration
uv run invoke test-unit                     # no Docker
uv run invoke test-integration              # requires Docker; --tier=core default
uv run invoke test-integration --tier=full  # adds the extended tier
```

### Validate Schemas

```bash
uv run infrahubctl schema check schemas/
```

### Validate Before Committing

Always run `uv run invoke format lint` and confirm it passes without errors before considering any change complete. Fix all reported issues (YAML lint, ruff, mypy, rumdl) before moving on. When modifying documentation files under `docs/`, also run `vale` on the changed files to catch style violations (branded terms, sentence case headings). If new proper nouns appear in headings, add them to `.vale/styles/Infrahub/sentence-case.yml` exceptions.

### Running CLI Tools

All Python CLI tools (e.g., `infrahubctl`, `pytest`, `invoke`) must be run via `uv run` to ensure they use the project's virtual environment. Never call them directly.
