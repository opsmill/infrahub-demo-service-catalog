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
uv run pytest
```

### Validate Schemas

```bash
uv run infrahubctl schema check schemas/
```

### Running CLI Tools

All Python CLI tools (e.g., `infrahubctl`, `pytest`, `invoke`) must be run via `uv run` to ensure they use the project's virtual environment. Never call them directly.
