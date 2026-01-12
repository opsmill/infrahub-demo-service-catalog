import logging
import warnings
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fast_depends import Provider, dependency_provider
from streamlit.testing.v1 import AppTest

from infrahub_sdk.client import InfrahubClient, InfrahubClientSync
from infrahub_sdk.protocols import CoreGenericRepository, CoreProposedChange
from infrahub_sdk.spec.object import ObjectFile
from infrahub_sdk.testing.docker import TestInfrahubDockerClient
from infrahub_sdk.testing.repository import GitRepo
from infrahub_sdk.yaml import SchemaFile
from service_catalog.infrahub import get_client
from service_catalog.protocols_async import LocationSite, ServiceDedicatedInternet

if TYPE_CHECKING:
    from infrahub_testcontainers.container import InfrahubDockerCompose

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

logger = logging.getLogger(__name__)

# Essential services for integration tests (excludes scraper and cadvisor which are optional metrics services)
ESSENTIAL_SERVICES = [
    "database",
    "message-queue",
    "cache",
    "task-manager",
    "task-manager-db",
    "infrahub-server",
    "infrahub-server-lb",
    "task-worker",
]


class TestServiceCatalog(TestInfrahubDockerClient):
    @pytest.fixture(scope="class")
    def infrahub_app(
        self, request: pytest.FixtureRequest, infrahub_compose: "InfrahubDockerCompose"
    ) -> Generator[dict[str, int], None, None]:
        """Override to start only essential services, excluding scraper and cadvisor."""
        tests_failed_before_class = request.session.testsfailed

        # Only start essential services to avoid scraper/cadvisor failures
        infrahub_compose.services = ESSENTIAL_SERVICES

        try:
            infrahub_compose.start()
        except Exception as exc:
            stdout, stderr = infrahub_compose.get_logs()
            raise Exception(
                f"Failed to start docker compose:\nStdout:\n{stdout}\nStderr:\n{stderr}"
            ) from exc

        yield infrahub_compose.get_services_port()

        # Cleanup
        tests_failed_during_class = request.session.testsfailed - tests_failed_before_class
        if tests_failed_during_class > 0:
            stdout, stderr = infrahub_compose.get_logs("infrahub-server", "task-worker")
            warnings.warn(
                f"Container logs:\nStdout:\n{stdout}\nStderr:\n{stderr}",
                stacklevel=2,
            )
        infrahub_compose.stop()

    @pytest.fixture(scope="class")
    def provider(self) -> Generator[Provider, None, None]:
        yield dependency_provider
        dependency_provider.clear()

    @pytest.fixture(scope="class")
    def default_branch(self) -> str:
        return "main"

    @pytest.fixture(scope="class")
    def schema_definition(self, schema_dir: Path) -> list[SchemaFile]:
        return list(SchemaFile.load_from_disk(paths=[schema_dir]))

    @pytest.fixture(scope="class")
    def override_client(self, provider: Provider, client_sync: InfrahubClientSync) -> None:
        """Override the client that will be returned by FastDepends."""

        def get_test_client(branch: str = "main") -> InfrahubClientSync:
            return client_sync

        provider.override(get_client, get_test_client)

    def test_schema_load(
        self, client_sync: InfrahubClientSync, schema_definition: list[SchemaFile], default_branch: str
    ) -> None:
        """Load the schema from the schema directory into the infrahub instance."""
        logger.info("Starting test: test_schema_load")

        client_sync.schema.load(schemas=[item.content for item in schema_definition])
        client_sync.schema.wait_until_converged(branch=default_branch)

    async def test_data_load(self, client: InfrahubClient, data_dir: Path, default_branch: str) -> None:
        """Load the data from the data directory into the infrahub instance."""
        logger.info("Starting test: test_data_load")

        await client.schema.all()
        object_files = sorted(ObjectFile.load_from_disk(paths=[data_dir]), key=lambda x: x.location)

        for idx, file in enumerate(object_files):
            file.validate_content()
            schema = await client.schema.get(kind=file.spec.kind, branch=default_branch)
            for item in file.spec.data:
                await file.spec.create_node(
                    client=client, position=[idx], schema=schema, data=item, branch=default_branch
                )

        sites = await client.all(kind=LocationSite)
        assert len(sites) == 3

    async def test_add_repository(
        self, client: InfrahubClient, root_dir: Path, default_branch: str, remote_repos_dir: Path
    ) -> None:
        """Add the local directory as a repository in the infrahub instance.

        This validates the import of the repository and ensures the generator is operational.
        """
        repo = GitRepo(name="infrahub-demo-service-catalog", src_directory=root_dir, dst_directory=remote_repos_dir)
        await repo.add_to_infrahub(client=client)
        in_sync = await repo.wait_for_sync_to_complete(client=client)
        assert in_sync

        repos = await client.all(kind=CoreGenericRepository)
        assert repos

    async def test_portal(self, override_client: None, client: InfrahubClient, default_branch: str) -> None:
        """Test the streamlit app on top of a running infrahub instance.

        Verifies that submitting the form:
        1. Creates a new branch
        2. Creates a service object on that branch
        3. Creates a proposed change targeting main
        """
        service_identifier = "test-12345"
        expected_branch_name = f"implement_{service_identifier.lower()}"

        app = AppTest.from_file("service_catalog/pages/1_🔌_Dedicated_Internet.py").run()

        app.text_input("input-service-identifier").set_value(service_identifier).run()
        app.text_input("input-account-reference").set_value("acct-12345").run()
        app.selectbox("select-location").select("bru01").run()
        app.selectbox("select-bandwidth").set_value(100).run()
        app.select_slider("select-ip-package").set_value("small").run()
        app.button("FormSubmitter:new_dedicated_internet_form-Submit").click().run(timeout=15)

        # Verify the branch was created
        branches = await client.branch.all()
        assert expected_branch_name in branches, f"Branch '{expected_branch_name}' was not created"

        # Verify the service was created on the new branch
        services = await client.all(kind=ServiceDedicatedInternet, branch=expected_branch_name)
        assert len(services) == 1, "Service was not created on the new branch"
        assert services[0].service_identifier.value == service_identifier

        # Verify the proposed change was created
        proposed_changes = await client.all(kind=CoreProposedChange)
        assert len(proposed_changes) == 1, "Proposed change was not created"
        assert proposed_changes[0].source_branch.value == expected_branch_name
        assert proposed_changes[0].destination_branch.value == default_branch
