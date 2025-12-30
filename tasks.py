import os
import sys
from pathlib import Path

from invoke import Context, task

CURRENT_DIRECTORY = Path(__file__).resolve()
DOCUMENTATION_DIRECTORY = CURRENT_DIRECTORY.parent / "docs"
MAIN_DIRECTORY_PATH = Path(__file__).parent

infrahub_address = os.getenv("INFRAHUB_ADDRESS")
base_compose_cmd: str = "docker compose"


@task
def build(context: Context, cache: bool = True) -> None:
    compose_cmd = base_compose_cmd + " build"
    if not cache:
        compose_cmd += " --no-cache"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(compose_cmd, pty=True)


@task
def start(context: Context, build: bool = False) -> None:
    compose_cmd = base_compose_cmd + " up -d"
    if build:
        compose_cmd += " --build"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(compose_cmd, pty=True)


@task
def stop(context: Context) -> None:
    compose_cmd = base_compose_cmd + " down"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(compose_cmd, pty=True)


@task
def destroy(context: Context) -> None:
    compose_cmd = base_compose_cmd + " down -v"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(compose_cmd, pty=True)


@task
def restart(context: Context) -> None:
    compose_cmd = base_compose_cmd + " restart"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(compose_cmd, pty=True)


@task(name="format")
def format_all(context: Context) -> None:
    """Run RUFF to format all Python files."""
    exec_cmds = ["ruff format .", "ruff check . --fix"]
    with context.cd(MAIN_DIRECTORY_PATH):
        for cmd in exec_cmds:
            context.run(cmd, pty=True)


@task
def lint_yaml(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with yamllint")
    exec_cmd = "yamllint ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_mypy(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with mypy")
    exec_cmd = "mypy --show-error-codes service_catalog"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_ruff(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with ruff")
    exec_cmd = "ruff check ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task(name="lint")
def lint_all(context: Context) -> None:
    """Run all linters."""
    lint_yaml(context)
    lint_ruff(context)
    lint_mypy(context)


@task(name="docs")
def docs_build(context: Context) -> None:
    """Build documentation website."""
    exec_cmd = "npm run build"

    with context.cd(DOCUMENTATION_DIRECTORY):
        output = context.run(exec_cmd)

    if output is not None and output.exited != 0:
        sys.exit(-1)
