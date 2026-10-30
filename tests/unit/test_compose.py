"""Compose file layering used by ``invoke start``, and the portal image definition.

The portal image is pulled by default. The dev compose file that builds it from the
checkout must be layered only on request, otherwise a plain ``invoke start`` would
build an image the user expects to pull.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tasks import get_compose_command

ROOT = Path(__file__).resolve().parents[2]
OVERRIDE = ROOT / "docker-compose.override.yml"
CATALOG_DEV = ROOT / "docker-compose.catalog-dev.yml"
PORTAL_DOCKERFILE = ROOT / "service_catalog" / "Dockerfile"
IMAGE = "registry.opsmill.io/opsmill/infrahub-demo-service-catalog-streamlit"
SEMAPHORE_DOCKERFILE = ROOT / "semaphore" / "Dockerfile"
SEMAPHORE_IMAGE = "registry.opsmill.io/opsmill/infrahub-demo-service-catalog-semaphore"


def test_default_invocation_layers_only_the_override_file() -> None:
    """A plain start uses the committed override and not the dev build file."""
    cmd = get_compose_command()

    assert f"-f {OVERRIDE}" in cmd
    assert str(CATALOG_DEV) not in cmd


def test_local_build_layers_the_dev_file_after_the_override() -> None:
    """A local build adds the dev file last, so its build block wins."""
    cmd = get_compose_command(local_build=True)

    assert cmd.index(str(OVERRIDE)) < cmd.index(str(CATALOG_DEV))


def test_override_runs_the_portal_from_the_published_image_without_building_it() -> None:
    """The override points the portal at the published image, so a start pulls it."""
    service = yaml.safe_load(OVERRIDE.read_text(encoding="utf-8"))["services"]["service-catalog"]

    assert IMAGE in service["image"]
    assert "build" not in service
    assert "command" not in service  # the image starts the portal itself
    assert service["ports"] == ["8501:8501"]


def test_the_infrahub_services_still_build_the_custom_image() -> None:
    """Only the portal moved to a published image: Infrahub keeps the image with the module in it."""
    services = yaml.safe_load(OVERRIDE.read_text(encoding="utf-8"))["services"]

    for name in ("infrahub-server", "task-worker", "task-manager"):
        assert services[name]["build"]["dockerfile"] == "Dockerfile"


def test_dev_file_builds_the_portal_from_the_repository_root_and_mounts_its_sources() -> None:
    """The build installs from pyproject.toml and uv.lock, so the build context is the root."""
    service = yaml.safe_load(CATALOG_DEV.read_text(encoding="utf-8"))["services"]["service-catalog"]

    assert service["build"] == {"context": ".", "dockerfile": "service_catalog/Dockerfile"}
    assert service["volumes"] == ["./service_catalog:/app/service_catalog"]


def test_portal_image_installs_what_the_portal_imports_at_the_locked_versions() -> None:
    """The image copies the package where its imports resolve, and starts the portal as a non-root user."""
    text = PORTAL_DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY --chown=app:app service_catalog/ ./service_catalog/" in text
    assert "ENV PYTHONPATH=/app" in text
    assert "uv export --frozen --no-dev" in text
    assert "USER app" in text
    assert 'CMD ["streamlit", "run", "service_catalog/portal.py"]' in text


def test_override_runs_semaphore_from_the_published_image_without_building_it() -> None:
    """The override points Semaphore at the published image, which holds the playbooks, so nothing is mounted."""
    service = yaml.safe_load(OVERRIDE.read_text(encoding="utf-8"))["services"]["semaphore"]

    assert SEMAPHORE_IMAGE in service["image"]
    assert "build" not in service
    assert "volumes" not in service
    assert service["ports"] == ["3000:3000"]


def test_dev_file_builds_semaphore_from_the_repository_root_and_mounts_the_playbooks() -> None:
    """The build copies ansible/ and installs from uv.lock, so the build context is the root."""
    service = yaml.safe_load(CATALOG_DEV.read_text(encoding="utf-8"))["services"]["semaphore"]

    assert service["build"] == {"context": ".", "dockerfile": "semaphore/Dockerfile"}
    assert service["volumes"] == ["./ansible:/opt/semaphore/playbooks"]


def test_semaphore_image_holds_the_playbooks_and_the_locked_sdk() -> None:
    """The image copies the playbooks, installs the SDK at the locked version where Ansible runs, and runs as semaphore."""
    text = SEMAPHORE_DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY --chown=semaphore ansible/ /opt/semaphore/playbooks/" in text
    assert "uv export --frozen --no-dev" in text
    assert '--python "$(command -v python3)"' in text
    assert "/api/ping" in text  # the healthcheck
    # Without the file, Semaphore does not reinstall the collection from Galaxy before each task
    assert "RUN rm /opt/semaphore/playbooks/requirements.yml" in text
    assert text.count("USER semaphore") == 1
    assert text.index("USER semaphore") > text.index("USER root")


def test_build_context_keeps_what_the_semaphore_image_copies() -> None:
    """The root .dockerignore must not exclude the files the Semaphore image copies."""
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert not {"ansible", "semaphore", "pyproject.toml", "uv.lock"} & ignored
