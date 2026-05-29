import os
import sys
import time
from pathlib import Path

import httpx
from invoke import Context, task

CURRENT_DIRECTORY = Path(__file__).resolve()
DOCUMENTATION_DIRECTORY = CURRENT_DIRECTORY.parent / "docs"
MAIN_DIRECTORY_PATH = Path(__file__).parent

infrahub_address = os.getenv("INFRAHUB_ADDRESS")
base_compose_cmd: str = "docker compose"

SEMAPHORE_URL = "http://localhost:3000"
SEMAPHORE_ADMIN = "admin"
SEMAPHORE_ADMIN_PASSWORD = "semaphore"  # noqa: S105
SEMAPHORE_PLAYBOOK_PATH = "/opt/semaphore/playbooks"


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


@task
def format_python(context: Context) -> None:
    """Run ruff to format all Python files."""
    exec_cmds = ["ruff format .", "ruff check . --fix"]
    with context.cd(MAIN_DIRECTORY_PATH):
        for cmd in exec_cmds:
            context.run(cmd, pty=True)


@task
def format_markdown(context: Context) -> None:
    """Run rumdl to format all Markdown files."""
    exec_cmd = "rumdl check --fix ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task(name="format")
def format_all(context: Context) -> None:
    """Run all formatters."""
    format_python(context)
    format_markdown(context)


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


@task
def lint_rumdl(context: Context) -> None:
    """Run rumdl to check all Markdown files."""
    print(" - Check code with rumdl")
    exec_cmd = "rumdl check ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task(name="lint")
def lint_all(context: Context) -> None:
    """Run all linters."""
    lint_yaml(context)
    lint_ruff(context)
    lint_mypy(context)
    lint_rumdl(context)


@task(name="docs")
def docs_build(context: Context) -> None:
    """Build documentation website."""
    exec_cmd = "npm run build"

    with context.cd(DOCUMENTATION_DIRECTORY):
        output = context.run(exec_cmd)

    if output is not None and output.exited != 0:
        sys.exit(-1)


class _SemaphoreClient:
    """Thin wrapper around httpx.Client for Semaphore API calls."""

    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=10)

    def wait_until_ready(self) -> None:
        delay = 2
        for attempt in range(1, 9):
            try:
                self._client.get("/api/ping")
                print("Semaphore is reachable.")
                return
            except httpx.HTTPError:  # noqa: PERF203
                print(f"Waiting for Semaphore (attempt {attempt}/8, retry in {delay}s)...")
                time.sleep(delay)
                delay = min(delay * 2, 60)
        print("ERROR: Semaphore not reachable after 8 attempts.")
        sys.exit(1)

    def login(self, admin: str, password: str) -> None:
        resp = self._client.post("/api/auth/login", json={"auth": admin, "password": password})
        if resp.status_code not in {200, 204}:
            print(f"ERROR: Login failed (status={resp.status_code}).")
            sys.exit(1)
        print("Authenticated successfully.")

    def find_or_create(
        self,
        list_url: str,
        create_url: str,
        name: str,
        payload: dict[str, object],
    ) -> int:
        """Find an existing resource by name or create it. Returns the resource id."""
        items: list[dict[str, object]] = self._client.get(list_url).json()
        for item in items:
            if item.get("name") == name:
                rid = int(str(item["id"]))
                print(f"  '{name}' already exists (id={rid}).")
                return rid

        resp = self._client.post(create_url, json=payload)
        resp.raise_for_status()
        rid = int(resp.json()["id"])
        print(f"  '{name}' created (id={rid}).")
        return rid


@task(name="init-semaphore")
def init_semaphore(
    context: Context,  # noqa: ARG001
    url: str = SEMAPHORE_URL,
    admin: str = SEMAPHORE_ADMIN,
    password: str = SEMAPHORE_ADMIN_PASSWORD,
    playbook_path: str = SEMAPHORE_PLAYBOOK_PATH,
) -> None:
    """Seed Semaphore with the project, repository, inventory, and task template.

    Fully idempotent — each resource is looked up by name before creation.
    Safe to run multiple times; existing resources are reused.
    """
    print("=== Semaphore Init ===")
    api = _SemaphoreClient(url)
    api.wait_until_ready()
    api.login(admin, password)

    print("Project...")
    project_id = api.find_or_create(
        "/api/projects",
        "/api/projects",
        "Service Catalog",
        {"name": "Service Catalog", "alert": False, "max_parallel_tasks": 0},
    )

    print("Key store...")
    key_id = api.find_or_create(
        f"/api/project/{project_id}/keys",
        f"/api/project/{project_id}/keys",
        "None",
        {"name": "None", "type": "none", "project_id": project_id},
    )

    print("Repository...")
    repo_id = api.find_or_create(
        f"/api/project/{project_id}/repositories",
        f"/api/project/{project_id}/repositories",
        "Local",
        {
            "name": "Local",
            "project_id": project_id,
            "git_url": playbook_path,
            "git_branch": "",
            "ssh_key_id": key_id,
        },
    )

    print("Inventory...")
    inv_id = api.find_or_create(
        f"/api/project/{project_id}/inventory",
        f"/api/project/{project_id}/inventory",
        "Infrahub",
        {
            "name": "Infrahub",
            "project_id": project_id,
            "inventory": "inventory.yml",
            "type": "file",
            "ssh_key_id": key_id,
        },
    )

    print("Environment...")
    env_id = api.find_or_create(
        f"/api/project/{project_id}/environment",
        f"/api/project/{project_id}/environment",
        "Empty",
        {"name": "Empty", "project_id": project_id, "json": "{}", "env": "{}"},
    )

    print("Task template...")
    api.find_or_create(
        f"/api/project/{project_id}/templates",
        f"/api/project/{project_id}/templates",
        "Deploy",
        {
            "name": "Deploy",
            "project_id": project_id,
            "repository_id": repo_id,
            "inventory_id": inv_id,
            "environment_id": env_id,
            "playbook": "deploy.yml",
            "type": "task",
            "app": "ansible",
        },
    )

    print("=== Semaphore init complete ===")


@task(name="init", pre=[init_semaphore])
def init(context: Context) -> None:
    """Initialize the demo."""
    exec_cmd = [
        "uv run infrahubctl object load bootstrap/repository.yaml",
        "uv run infrahubctl object load bootstrap/permissions.yml",
    ]
    with context.cd(MAIN_DIRECTORY_PATH):
        for cmd in exec_cmd:
            output = context.run(cmd)
            if output is not None and output.exited != 0:
                sys.exit(-1)
