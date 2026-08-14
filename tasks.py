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

INFRAHUB_VERSION = os.getenv("INFRAHUB_VERSION", "stable")
INFRAHUB_ENTERPRISE = os.getenv("INFRAHUB_ENTERPRISE", "false").lower() == "true"
INFRAHUB_PROJECT_NAME = os.getenv("INFRAHUB_PROJECT_NAME", MAIN_DIRECTORY_PATH.name)


def get_compose_command() -> str:
    """Build the ``docker compose`` command with layered compose-file support.

    Resolution order for the base stack definition:
    1. Local ``docker-compose.yml`` (committed) when it exists.
    2. Otherwise a fresh base stack is downloaded from infrahub.opsmill.io and
       piped to ``docker compose`` over stdin.

    ``docker-compose.override.yml`` is always layered on top when present; in
    this repo it wires every service to the custom image built from the local
    ``Dockerfile``. The Compose project name is controlled by
    ``INFRAHUB_PROJECT_NAME`` and defaults to the directory name.

    Returns:
        The ``docker compose`` command prefix, ready for a subcommand suffix.
    """
    local_compose_file = MAIN_DIRECTORY_PATH / "docker-compose.yml"
    override_file = MAIN_DIRECTORY_PATH / "docker-compose.override.yml"

    base_cmd = f"docker compose -p {INFRAHUB_PROJECT_NAME}"

    if local_compose_file.exists():
        cmd = f"{base_cmd} -f {local_compose_file}"
    else:
        edition = "enterprise/" if INFRAHUB_ENTERPRISE else ""
        base_url = f"https://infrahub.opsmill.io/{edition}{INFRAHUB_VERSION}"
        cmd = f"curl -s {base_url} | {base_cmd} -f -"

    if override_file.exists():
        cmd += f" -f {override_file}"
    return cmd


def get_compose_source() -> str:
    """Describe where the base compose definition comes from.

    Returns:
        A short human-readable description of the compose source.
    """
    if (MAIN_DIRECTORY_PATH / "docker-compose.yml").exists():
        return "Local (docker-compose.yml)"

    edition = "Enterprise" if INFRAHUB_ENTERPRISE else "Community"
    return f"infrahub.opsmill.io ({edition} {INFRAHUB_VERSION})"


COMPOSE_COMMAND = get_compose_command()
COMPOSE_SOURCE = get_compose_source()

SEMAPHORE_URL = "http://localhost:3000"
SEMAPHORE_ADMIN = "admin"
SEMAPHORE_ADMIN_PASSWORD = "semaphore"  # noqa: S105
SEMAPHORE_PLAYBOOK_PATH = "/opt/semaphore/playbooks"


@task
def build(context: Context, cache: bool = True) -> None:
    """Build the Docker Compose images for the service catalog stack."""
    compose_cmd = COMPOSE_COMMAND + " build"
    if not cache:
        compose_cmd += " --no-cache"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(compose_cmd, pty=True)


@task
def start(context: Context, build: bool = False) -> None:
    """Start the service catalog stack in the background via Docker Compose."""
    print(f"Compose source: {COMPOSE_SOURCE}")
    compose_cmd = COMPOSE_COMMAND + " up -d"
    if build:
        compose_cmd += " --build"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(compose_cmd, pty=True)


@task
def stop(context: Context) -> None:
    """Stop the service catalog stack and remove containers."""
    compose_cmd = COMPOSE_COMMAND + " down"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(compose_cmd, pty=True)


@task
def destroy(context: Context) -> None:
    """Stop the stack and delete all associated volumes (irreversible)."""
    compose_cmd = COMPOSE_COMMAND + " down -v"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(compose_cmd, pty=True)


@task
def restart(context: Context) -> None:
    """Restart all running containers in the service catalog stack."""
    compose_cmd = COMPOSE_COMMAND + " restart"
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
    """Run all code formatters (ruff for Python, rumdl for Markdown)."""
    format_python(context)
    format_markdown(context)


@task
def lint_yaml(context: Context) -> None:
    """Lint all YAML files with yamllint."""
    print(" - Check code with yamllint")
    exec_cmd = "yamllint ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_mypy(context: Context) -> None:
    """Type-check the service_catalog package with mypy."""
    print(" - Check code with mypy")
    exec_cmd = "mypy --show-error-codes service_catalog"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_ruff(context: Context) -> None:
    """Lint all Python files with ruff."""
    print(" - Check code with ruff")
    exec_cmd = "ruff check ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_rumdl(context: Context) -> None:
    """Lint all Markdown files with rumdl."""
    print(" - Check code with rumdl")
    exec_cmd = "rumdl check ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task(name="lint")
def lint_all(context: Context) -> None:
    """Run all linters (yamllint, ruff, mypy, rumdl)."""
    lint_yaml(context)
    lint_ruff(context)
    lint_mypy(context)
    lint_rumdl(context)


@task(name="test-unit")
def test_unit(context: Context) -> None:
    """Run the unit test suite (no Docker required)."""
    exec_cmd = "pytest tests/unit"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task(name="test-integration")
def test_integration(context: Context) -> None:
    """Run the integration test suite against a Dockerized Infrahub instance."""
    exec_cmd = "pytest tests/integration"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task(name="test")
def test_all(context: Context) -> None:
    """Run the full test suite (unit and integration)."""
    test_unit(context)
    test_integration(context)


@task(name="docs")
def docs_build(context: Context) -> None:
    """Build the documentation website with Docusaurus (npm run build)."""
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
    """Initialize the demo: seed Semaphore, then load the repository and permissions into Infrahub."""
    exec_cmd = [
        "uv run infrahubctl object load bootstrap/repository.yaml",
        "uv run infrahubctl object load bootstrap/permissions.yml",
    ]
    with context.cd(MAIN_DIRECTORY_PATH):
        for cmd in exec_cmd:
            output = context.run(cmd)
            if output is not None and output.exited != 0:
                sys.exit(-1)
