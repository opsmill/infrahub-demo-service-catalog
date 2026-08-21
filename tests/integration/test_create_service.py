import ipaddress
import logging
from collections.abc import Generator
from pathlib import Path

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
from service_catalog.protocols_async import (
    DcimInterface,
    DcimInterfaceL2,
    IpamIPAddress,
    IpamPrefix,
    IpamVLAN,
    LocationSite,
    ServiceDedicatedInternet,
)

GENERATOR_SERVICE_IDENTIFIER = "test-generator-1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

logger = logging.getLogger(__name__)


class TestServiceCatalog(TestInfrahubDockerClient):
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
        assert {site.shortname.value for site in sites} == {"par01", "bru01", "nyc01", "dal01"}

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

    async def test_generator_allocation(self, client: InfrahubClient, infrahub_port: int, default_branch: str) -> None:
        """Run the generator directly and verify it allocates a VLAN/prefix/port/gateway, twice.

        Running the generator a second time on the same service must not create duplicate
        resources; this is a regression test for the HFID/upsert fix in `allocate_vlan`
        (see generators/implement_dedicated_internet.py).
        """
        service = await client.create(
            kind=ServiceDedicatedInternet,
            service_identifier=GENERATOR_SERVICE_IDENTIFIER,
            account_reference="acct-generator-1",
            status="draft",
            bandwidth="100",
            ip_package="small",
            member_of_groups=["automated_dedicated_internet"],
            location=["bru01"],
            branch=default_branch,
        )
        await service.save()

        command = (
            f"infrahubctl generator dedicated_internet_generator "
            f"--branch {default_branch} service_identifier={GENERATOR_SERVICE_IDENTIFIER}"
        )
        address = f"http://localhost:{infrahub_port}"
        for _ in range(2):
            result = self.execute_command(command=command, address=address)
            assert result.returncode == 0, f"Generator run failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

        service = await client.get(
            kind=ServiceDedicatedInternet,
            service_identifier__value=GENERATOR_SERVICE_IDENTIFIER,
            branch=default_branch,
        )

        # Each allocation is read from its *owning* side rather than through the service. `vlan`,
        # `prefix`, `gateway_ip_address` and `dedicated_interfaces` are all `direction: inbound`
        # (schemas/service/service.yml), and infrahub-sdk >=1.23 raises on `fetch()` for a
        # relationship the query left unresolved instead of resolving it lazily. Querying the side
        # that stores the link avoids that entirely, and makes a missing allocation report itself as
        # a count rather than as an SDK error.
        #
        # "exactly one" is also the assertion that the *second* generator run reused each resource
        # instead of duplicating it, which is what this test exists to pin down.
        vlans = await client.filters(kind=IpamVLAN, service__ids=[service.id], branch=default_branch)
        assert len(vlans) == 1, "the generator must allocate exactly one VLAN, and reuse it on re-runs"
        vlan = vlans[0]
        assert 1000 <= vlan.vlan_id.value <= 2000

        prefixes = await client.filters(kind=IpamPrefix, service__ids=[service.id], branch=default_branch)
        assert len(prefixes) == 1, "the generator must allocate exactly one prefix, and reuse it on re-runs"
        # IPv4Network rather than ip_network(): the latter returns IPv4Network | IPv6Network, and
        # subnet_of() requires both sides to be the same family, so mypy cannot prove the call is
        # valid. This service allocates from an IPv4 pool, so name the family.
        allocated_network = ipaddress.IPv4Network(str(prefixes[0].prefix.value))
        assert allocated_network.prefixlen == 29
        assert allocated_network.subnet_of(ipaddress.IPv4Network("203.0.113.0/24"))

        gateways = await client.filters(kind=IpamIPAddress, service__ids=[service.id], branch=default_branch)
        assert len(gateways) == 1, "the generator must allocate exactly one gateway address"

        # Both the L2 customer port (allocate_port) and the L3 gateway interface (allocate_gateway)
        # inherit from DcimInterface and share the "service" identifier, hence two.
        interfaces = await client.filters(kind=DcimInterface, service__ids=[service.id], branch=default_branch)
        assert len(interfaces) == 2

        l2_ports = await client.filters(
            kind=DcimInterfaceL2, service__ids=[service.id], branch=default_branch, include=["untagged_vlan"]
        )
        assert len(l2_ports) == 1
        port = l2_ports[0]
        assert port.status.value == "active"
        assert port.role.value == "customer"
        assert port.untagged_vlan.id == vlan.id, "the allocated port must carry the allocated VLAN untagged"

    async def test_artifact_rendering(self, client: InfrahubClient, infrahub_port: int, default_branch: str) -> None:
        """Verify the startup-config transform renders the VLAN/port allocated by the generator.

        Uses `infrahubctl render` (like the generator test uses `infrahubctl generator`) to render
        the transform directly against current data, rather than the artifact-generation pipeline:
        the artifact for this device was already rendered once (stale) when the repository synced,
        and re-triggering that pipeline on demand did not reliably produce an updated render.
        """
        service = await client.get(
            kind=ServiceDedicatedInternet,
            service_identifier__value=GENERATOR_SERVICE_IDENTIFIER,
            branch=default_branch,
        )

        l2_ports = await client.filters(
            kind=DcimInterfaceL2, service__ids=[service.id], branch=default_branch, include=["device"]
        )
        port = l2_ports[0]
        await port.device.fetch()
        device = port.device.peer

        # From the owning side, for the same reason as in test_generator_allocation.
        vlans = await client.filters(kind=IpamVLAN, service__ids=[service.id], branch=default_branch)
        assert len(vlans) == 1
        vlan = vlans[0]

        address = f"http://localhost:{infrahub_port}"
        command = f"infrahubctl render device_config --branch {default_branch} device_name={device.name.value}"
        result = self.execute_command(command=command, address=address)
        assert result.returncode == 0, f"Render failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        content = result.stdout

        assert f"switchport access vlan {vlan.vlan_id.value}" in content
        assert f'description "Port allocated to service {GENERATOR_SERVICE_IDENTIFIER}"' in content

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
        app.selectbox("select-bandwidth").set_value("100").run()
        app.select_slider("select-ip-package").set_value("small").run()
        app.button("FormSubmitter:new_dedicated_internet_form-Submit").click().run(timeout=15)

        # Verify the branch was created
        branches = await client.branch.all()
        assert expected_branch_name in branches, f"Branch '{expected_branch_name}' was not created"

        # Verify the service was created on the new branch. `ServiceDedicatedInternet` is
        # branch-agnostic, so other services created by earlier tests are visible here too;
        # filter by identifier rather than asserting on the raw count.
        services = await client.all(kind=ServiceDedicatedInternet, branch=expected_branch_name)
        matches = [service for service in services if service.service_identifier.value == service_identifier]
        assert len(matches) == 1, "Service was not created on the new branch"

        # Verify the proposed change was created
        proposed_changes = await client.all(kind=CoreProposedChange)
        assert len(proposed_changes) == 1, "Proposed change was not created"
        assert proposed_changes[0].source_branch.value == expected_branch_name
        assert proposed_changes[0].destination_branch.value == default_branch
