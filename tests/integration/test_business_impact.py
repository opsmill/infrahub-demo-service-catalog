"""Blast radius and the Gold outage guard against a live Infrahub.

Loads the schema and data (including `data/10_customers_tiers.yml`), imports the repository so
the stored query `business_impact_services` and the generator definition exist, runs the seed
steps (the generator through `infrahubctl`), then runs the stored query on main and on both
maintenance branches and feeds `blast_radius.py`.

After the seed it asserts the Gold outage guard: its validator fails on the
Paris and Brussels proposed changes with the messages the docs show and passes on New York, and Infrahub
refuses to merge the Paris proposed change. The stack runs the stock Infrahub image, where
`service_catalog` is not installed, so the guard's messages also record that the task worker
imports `service_catalog.business_impact` from the repository.

It also records open checks: whether `role__values` works, whether opening a
proposed change reruns the generator, whether `customer`, `tier` and `monthly_charge` survive the
generator runs, and whether a customer named "Equinix" is refused by the name uniqueness that
`OrganizationGeneric` shares with providers.
The last test prints them all; run with `-rP` to see it.

Marked `extended`: the proposed change pipelines alone take several minutes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

from infrahub_sdk.exceptions import GraphQLError
from infrahub_sdk.protocols import (
    CoreCheckDefinition,
    CoreGeneratorInstance,
    CoreProposedChange,
    CoreStandardCheck,
    CoreValidator,
)
from infrahub_sdk.spec.object import ObjectFile
from infrahub_sdk.testing.docker import TestInfrahubDockerClient
from infrahub_sdk.testing.repository import GitRepo
from infrahub_sdk.yaml import SchemaFile
from service_catalog.business_impact import seed
from service_catalog.business_impact.blast_radius import BlastRadius, build_blast_radius, format_eur, parse_devices
from service_catalog.infrahub import run_query
from service_catalog.protocols_sync import DcimDevice, OrganizationCustomer
from tests.unit.test_gold_outage_guard import BRUSSELS_MESSAGE, PARIS_MESSAGE

if TYPE_CHECKING:
    from pathlib import Path

    from infrahub_sdk.client import InfrahubClient, InfrahubClientSync

pytestmark = pytest.mark.extended

logger = logging.getLogger(__name__)

QUERY_NAME = "business_impact_services"
PARIS = "maint-rb01-par01"
BRUSSELS = "maint-sw01-bru01"

MERGE_MUTATION = """
mutation MergeProposedChange($id: String!) {
  CoreProposedChangeMerge(data: {id: $id}, wait_until_completion: true) {
    ok
  }
}
"""

# Open-check results, filled by the tests and printed by the last one.
OPEN_CHECKS: dict[str, str] = {}


def _q1(client_sync: InfrahubClientSync, branch: str) -> dict[str, Any]:
    return run_query(name=QUERY_NAME, branch=branch, client=client_sync)


def _business_fields(data: dict[str, Any]) -> dict[str, tuple[str | None, str | None, int | None]]:
    """Customer, tier and monthly charge per service identifier, as the query reads them."""
    fields = {}
    for edge in data["ServiceDedicatedInternet"]["edges"]:
        node = edge["node"]
        customer = (node["customer"] or {}).get("node") or {}
        tier = (node["tier"] or {}).get("node") or {}
        fields[node["service_identifier"]["value"]] = (
            (customer.get("name") or {}).get("value"),
            (tier.get("name") or {}).get("value"),
            (node["monthly_charge"] or {}).get("value"),
        )
    return fields


EXPECTED_FIELDS = {row.service_identifier: (row.customer, row.tier, row.monthly_charge) for row in seed.SEED_SERVICES}


def _assert_fields_survive(client_sync: InfrahubClientSync, branch: str) -> None:
    fields = _business_fields(_q1(client_sync, branch))
    seeded = {identifier: fields.get(identifier) for identifier in EXPECTED_FIELDS}
    OPEN_CHECKS[f"customer, tier and monthly_charge survive on {branch}"] = str(seeded == EXPECTED_FIELDS)
    assert seeded == EXPECTED_FIELDS


def _tiles(result: BlastRadius) -> dict[str, str]:
    return {tile.label: tile.value for tile in result.tiles}


class TestBusinessImpact(TestInfrahubDockerClient):
    @pytest.fixture(scope="class")
    def default_branch(self) -> str:
        return "main"

    @pytest.fixture(scope="class")
    def address(self, infrahub_port: int) -> str:
        return f"http://localhost:{infrahub_port}"

    def test_schema_load(self, client_sync: InfrahubClientSync, schema_dir: Path, default_branch: str) -> None:
        schemas = list(SchemaFile.load_from_disk(paths=[schema_dir]))
        client_sync.schema.load(schemas=[item.content for item in schemas])
        client_sync.schema.wait_until_converged(branch=default_branch)

    async def test_data_load(self, client: InfrahubClient, data_dir: Path, default_branch: str) -> None:
        await client.schema.all()
        object_files = sorted(ObjectFile.load_from_disk(paths=[data_dir]), key=lambda x: x.location)
        assert any(file.location.name == "10_customers_tiers.yml" for file in object_files)
        for idx, file in enumerate(object_files):
            file.validate_content()
            schema = await client.schema.get(kind=file.spec.kind, branch=default_branch)
            for item in file.spec.data:
                await file.spec.create_node(
                    client=client, position=[idx], schema=schema, data=item, branch=default_branch
                )

    async def test_add_repository(self, client: InfrahubClient, root_dir: Path, remote_repos_dir: Path) -> None:
        """Import the working tree, which registers the stored query and the generator definition."""
        repo = GitRepo(name="infrahub-demo-service-catalog", src_directory=root_dir, dst_directory=remote_repos_dir)
        await repo.add_to_infrahub(client=client)
        assert await repo.wait_for_sync_to_complete(client=client, retries=24)

    def test_gold_outage_guard_definition_imported(self, client_sync: InfrahubClientSync) -> None:
        """The repository import registers the check definition."""
        names = sorted(str(definition.name.value) for definition in client_sync.all(kind=CoreCheckDefinition))
        OPEN_CHECKS["check definitions on main"] = ", ".join(names)

        assert "gold_outage_guard" in names
        # The check runs the Blast radius view's stored query: Infrahub links it from `GoldOutageGuard.query`.
        guard = client_sync.get(kind=CoreCheckDefinition, name__value="gold_outage_guard", prefetch_relationships=True)
        assert guard.query.peer.name.value == QUERY_NAME

    def test_seed_services_and_generators(self, client_sync: InfrahubClientSync, address: str) -> None:
        seed.wait_for_repository(client_sync)
        seed.seed_services(client_sync)

        def run(command: str) -> None:
            result = self.execute_command(command=command, address=address)
            if result.returncode != 0:
                raise seed.SeedError(f"exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")

        seed.run_generators(client_sync, run)
        _assert_fields_survive(client_sync, "main")

    def test_seed_is_idempotent_for_services(self, client_sync: InfrahubClientSync) -> None:
        """A second run of steps 1-2 leaves every service active and does not pin another port."""
        seed.seed_services(client_sync)
        data = _q1(client_sync, "main")
        statuses = {
            edge["node"]["service_identifier"]["value"]: edge["node"]["status"]["value"]
            for edge in data["ServiceDedicatedInternet"]["edges"]
        }
        assert all(statuses[row.service_identifier] == "active" for row in seed.SEED_SERVICES)

    def test_seed_maintenance(self, client_sync: InfrahubClientSync) -> None:
        main_instances = len(client_sync.all(kind=CoreGeneratorInstance, branch="main"))
        seed.seed_maintenance(client_sync)

        for change in seed.MAINTENANCE_CHANGES:
            proposed_change = client_sync.get(kind=CoreProposedChange, name__value=change.proposed_change_name)
            validators = client_sync.filters(kind=CoreValidator, proposed_change__ids=[proposed_change.id])
            kinds = sorted({str(validator.typename) for validator in validators})
            generator_validators = [validator for validator in validators if "Generator" in str(validator.typename)]
            instances = len(client_sync.all(kind=CoreGeneratorInstance, branch=change.branch))
            OPEN_CHECKS[f"validators on {change.branch}"] = ", ".join(kinds)
            OPEN_CHECKS[f"generator reran on {change.branch}"] = (
                f"{bool(generator_validators)} ({len(generator_validators)} generator validators; "
                f"generator instances on main {main_instances}, on the branch {instances})"
            )
            _assert_fields_survive(client_sync, change.branch)

    def _guard(self, client_sync: InfrahubClientSync, name: str) -> tuple[str | None, str]:
        """Conclusion of the Gold outage guard validator on a proposed change, and its check messages."""
        proposed_change = client_sync.get(kind=CoreProposedChange, name__value=name)
        validators = client_sync.filters(kind=CoreValidator, proposed_change__ids=[proposed_change.id])
        guard = [validator for validator in validators if validator.label.value == seed.GUARD_VALIDATOR_LABEL]
        assert len(guard) == 1, f"{name}: validators {[validator.label.value for validator in validators]}"
        checks = client_sync.filters(kind=CoreStandardCheck, validator__ids=[guard[0].id])
        return guard[0].conclusion.value, "\n".join(str(check.message.value or "") for check in checks)

    @pytest.mark.parametrize(
        ("name", "message"),
        [("Paris router 1 maintenance", PARIS_MESSAGE), ("Brussels switch 1 maintenance", BRUSSELS_MESSAGE)],
        ids=["paris", "brussels"],
    )
    def test_gold_outage_guard_fails(self, client_sync: InfrahubClientSync, name: str, message: str) -> None:
        """The guard fails with the message the docs show."""
        conclusion, messages = self._guard(client_sync, name)
        OPEN_CHECKS[f"Gold outage guard on {name}"] = f"{conclusion}: {messages.strip()!r}"

        assert conclusion == "failure"
        assert message in messages
        # The rule lives in service_catalog.business_impact, so its message proves the worker imported it.
        OPEN_CHECKS["task worker imports service_catalog.business_impact (stock image)"] = "True"

    def test_gold_outage_guard_passes_on_new_york(self, client_sync: InfrahubClientSync) -> None:
        """No active service runs through `rb01-nyc01`."""
        conclusion, messages = self._guard(client_sync, "New York router 1 maintenance")
        OPEN_CHECKS["Gold outage guard on New York router 1 maintenance"] = f"{conclusion}: {messages.strip()!r}"

        assert conclusion == "success"
        assert "Check succesfully completed" in messages

    def test_merge_refused_on_paris(self, client_sync: InfrahubClientSync) -> None:
        """Infrahub refuses to merge a proposed change whose guard failed."""
        proposed_change = client_sync.get(kind=CoreProposedChange, name__value="Paris router 1 maintenance")
        # Infrahub refuses a merge when any validator other than data integrity did not succeed, so first show
        # that the Gold outage guard is the only one that failed: the refusal is then the guard's.
        validators = client_sync.filters(kind=CoreValidator, proposed_change__ids=[proposed_change.id])
        conclusions = {str(validator.label.value): validator.conclusion.value for validator in validators}
        OPEN_CHECKS["validator conclusions on Paris router 1 maintenance"] = str(conclusions)
        failing = sorted(
            label for label, conclusion in conclusions.items() if conclusion != "success" and label != "Data Integrity"
        )
        assert failing == [seed.GUARD_VALIDATOR_LABEL]
        try:
            response = client_sync.execute_graphql(query=MERGE_MUTATION, variables={"id": proposed_change.id})
            surface = f"mutation returned {response}"
        except GraphQLError as exc:
            surface = f"mutation raised GraphQLError: {exc.errors[0].get('message') if exc.errors else exc}"

        after = client_sync.get(kind=CoreProposedChange, id=proposed_change.id)
        router = client_sync.get(kind=DcimDevice, name__value="rb01-par01", branch="main")
        OPEN_CHECKS["merge of Paris router 1 maintenance"] = (
            f"{surface}; state after: {after.state.value}; rb01-par01 on main: {router.status.value}"
        )

        assert after.state.value == "open"
        assert router.status.value == "active"

    def test_role_values_filter(self, client_sync: InfrahubClientSync) -> None:
        """The `role__values` filter returns the 16 core and edge devices."""
        try:
            devices = parse_devices(_q1(client_sync, "main"))
        except (RuntimeError, GraphQLError) as exc:
            OPEN_CHECKS["role__values works"] = f"False ({exc})"
            raise
        roles = {device.role for device in devices}
        OPEN_CHECKS["role__values works"] = (
            f"{roles <= {'core', 'edge'} and len(devices) == 16} ({len(devices)} devices, roles {sorted(str(role) for role in roles)})"
        )
        assert roles == {"core", "edge"}
        assert len(devices) == 16
        assert all(device.site for device in devices), "every device must carry its site shortname"

    def test_blast_radius_paris(self, client_sync: InfrahubClientSync) -> None:
        result = build_blast_radius(_q1(client_sync, PARIS), _q1(client_sync, "main"))

        assert result.headline == "This change takes 2 Gold services for Northbank out of service"
        assert _tiles(result) == {
            "Customers affected": "3",
            "Gold services affected": "2 of 5",
            "Gold SLA credit exposure, per month": "€2,565",
        }
        northbank = next(value for value in result.customer_values if value.customer == "Northbank")
        assert (format_eur(northbank.affected_annual), format_eur(northbank.annual)) == ("€123,120", "€149,040")
        affected = {value.customer: value.affected_annual for value in result.customer_values}
        assert affected == {"Helix Health": 0, "Maison Verte": 18_720, "Northbank": 123_120, "Rapid Freight": 4_800}
        assert [row.service for row in result.affected_rows] == ["DI-1001", "DI-1002", "DI-1004", "DI-1006"]
        assert result.affected_rows[0].edge_router == "Paris edge router 1"
        assert [(row.label, row.in_this_change) for row in result.routers] == [
            ("Paris edge router 1", True),
            ("Brussels edge router 1", False),
            ("Paris edge router 2", False),
            ("Brussels edge router 2", False),
        ]

    def test_blast_radius_brussels(self, client_sync: InfrahubClientSync) -> None:
        result = build_blast_radius(_q1(client_sync, BRUSSELS), _q1(client_sync, "main"))

        assert result.headline == "This change takes 1 Gold service for Helix Health out of service"
        assert _tiles(result) == {
            "Customers affected": "3",
            "Gold services affected": "1 of 5",
            "Gold SLA credit exposure, per month": "€2,025",
        }

    def test_blast_radius_main(self, client_sync: InfrahubClientSync) -> None:
        main = _q1(client_sync, "main")
        result = build_blast_radius(main, main)

        assert result.headline == "No service is affected"
        assert _tiles(result) == {
            "Customers affected": "0",
            "Gold services affected": "0 of 5",
            "Gold SLA credit exposure, per month": "€0",
        }

    def test_customer_name_shared_with_provider(self, client_sync: InfrahubClientSync) -> None:
        """`OrganizationGeneric.name` is unique across customers, providers and manufacturers."""
        customer = client_sync.create(kind=OrganizationCustomer, name="Equinix", branch="main")
        try:
            customer.save()
        except GraphQLError as exc:
            OPEN_CHECKS['customer named "Equinix" refused'] = (
                f"True ({exc.errors[0].get('message') if exc.errors else exc})"
            )
            return
        OPEN_CHECKS['customer named "Equinix" refused'] = "False (the customer was created)"
        customer.delete()

    def test_report_open_checks(self) -> None:
        print("\nOpen checks:")
        for check, result in OPEN_CHECKS.items():
            print(f"- {check}: {result}")
        assert OPEN_CHECKS
