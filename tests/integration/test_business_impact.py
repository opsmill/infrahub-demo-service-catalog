"""Blast radius and the Gold outage guard against a live Infrahub.

Loads the schema and data (including `data/10_customers_tiers.yml`), imports the repository so
the stored query `business_impact_services` and the generator definition exist, runs the seed
steps (the generator through `infrahubctl`), then runs the stored query on main and on both
maintenance branches and feeds `blast_radius.py`.

After the seed it asserts the Gold outage guard: its validator fails on the
Paris and Brussels proposed changes with the messages the docs show and passes on New York, it fails
on a proposed change that deletes Brussels edge router 1, it fails on a proposed change that raises
the Silver rule to 2 separate paths, and Infrahub refuses to merge the Paris proposed change and the
Silver rule change. The stack runs the stock Infrahub image, where
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
from service_catalog.business_impact.gold_outage_guard import MAX_HOPS, NETWORK_KINDS, tier_rules
from service_catalog.infrahub import run_query
from service_catalog.protocols_sync import (
    DcimDevice,
    DcimInterfaceL2,
    DcimInterfaceL3,
    OrganizationCustomer,
    ServiceDedicatedInternet,
    ServiceTier,
)
from tests.unit.test_gold_outage_guard import BRUSSELS_MESSAGE, PARIS_MESSAGE, RAISE_SILVER, RAISE_SILVER_MESSAGE

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from infrahub_sdk.client import InfrahubClient, InfrahubClientSync

pytestmark = pytest.mark.extended

logger = logging.getLogger(__name__)

QUERY_NAME = "business_impact_services"
PARIS = "maint-rb01-par01"
BRUSSELS = "maint-sw01-bru01"
MOVED = "maint-rb01-par01-moved"
MOVED_NAME = "Paris router 1 maintenance, Gold services moved first"
DELETED = "delete-rb01-bru01"
DELETED_NAME = "Delete Brussels router 1"
DELETED_MESSAGE = (
    "Delete Brussels router 1 leaves 1 Gold service for Helix Health with no other path (DI-2001). "
    "Gold SLA credit exposure: €2,025 per month (demo business input). "
    "Move this service to Brussels edge router 2 first."
)
RAISED = "raise-silver-rule"

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


class TestBusinessImpact(TestInfrahubDockerClient):  # noqa: PLR0904 - one test per step of the storyline
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

    def _runner(self, address: str) -> Callable[[str], None]:
        """Run an `infrahubctl` command against the test server; raise `SeedError` when it exits non-zero."""

        def run(command: str) -> None:
            result = self.execute_command(command=command, address=address)
            if result.returncode != 0:
                raise seed.SeedError(f"exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")

        return run

    def test_seed_services_and_generators(self, client_sync: InfrahubClientSync, address: str) -> None:
        seed.wait_for_repository(client_sync)
        seed.seed_services(client_sync)
        seed.run_generators(client_sync, self._runner(address))
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

    def test_seed_maintenance(self, client_sync: InfrahubClientSync, address: str) -> None:
        main_instances = len(client_sync.all(kind=CoreGeneratorInstance, branch="main"))
        seed.seed_maintenance(client_sync, self._runner(address))

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

    @staticmethod
    def _wait_for_guard(client_sync: InfrahubClientSync, proposed_change_id: str, name: str) -> None:
        """Wait until the Gold outage guard validator of a proposed change has finished."""

        def finished() -> bool:
            validators = client_sync.filters(kind=CoreValidator, proposed_change__ids=[proposed_change_id])
            rows = [
                seed.ValidatorRow(label=node.label.value, state=node.state.value, conclusion=node.conclusion.value)
                for node in validators
            ]
            return seed.validators_finished(rows, required=(seed.GUARD_VALIDATOR_LABEL,))

        seed.wait_until(finished, seed.PIPELINE_TIMEOUT_S, f"the pipeline of {name}")

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
        assert "Gold requires at least 1 separate path during a change, and this change leaves 0." in messages
        # The rule lives in service_catalog.business_impact, so its message proves the worker imported it.
        OPEN_CHECKS["task worker imports service_catalog.business_impact (stock image)"] = "True"

    def test_gold_outage_guard_passes_on_new_york(self, client_sync: InfrahubClientSync) -> None:
        """No active service runs through `rb01-nyc01`."""
        conclusion, messages = self._guard(client_sync, "New York router 1 maintenance")
        OPEN_CHECKS["Gold outage guard on New York router 1 maintenance"] = f"{conclusion}: {messages.strip()!r}"

        assert conclusion == "success"
        assert "Check succesfully completed" in messages
        assert "New York router 1 maintenance leaves no active Gold service without a path." in messages

    def test_gold_outage_guard_fails_when_a_device_is_deleted(self, client_sync: InfrahubClientSync) -> None:
        """Deleting Brussels edge router 1 removes DI-2001's gateway with it: no device is left with a status
        to check, and the guard still fails because DI-2001 has no edge router on the branch.
        """
        client_sync.branch.create(branch_name=DELETED, sync_with_git=False, description=DELETED_NAME)
        router = client_sync.get(kind=DcimDevice, name__value="rb01-bru01", branch=DELETED)
        router.delete()

        proposed_change = client_sync.create(
            kind=CoreProposedChange,
            branch="main",
            name=DELETED_NAME,
            source_branch=DELETED,
            destination_branch="main",
        )
        proposed_change.save()
        self._wait_for_guard(client_sync, proposed_change.id, DELETED_NAME)

        conclusion, messages = self._guard(client_sync, DELETED_NAME)
        OPEN_CHECKS[f"Gold outage guard on {DELETED_NAME}"] = f"{conclusion}: {messages.strip()!r}"

        assert conclusion == "failure"
        assert DELETED_MESSAGE in messages

    def test_tightening_a_tier_rule_fails(self, client_sync: InfrahubClientSync) -> None:
        """Raising the Silver rule from 0 to 2 fails, because each active Silver service has 1 path, and
        Infrahub refuses to merge the proposed change.
        """
        client_sync.branch.create(branch_name=RAISED, sync_with_git=False, description=RAISE_SILVER)
        silver = client_sync.get(kind=ServiceTier, name__value="Silver", branch=RAISED)
        silver.min_paths.value = 2
        silver.save()

        proposed_change = client_sync.create(
            kind=CoreProposedChange,
            branch="main",
            name=RAISE_SILVER,
            source_branch=RAISED,
            destination_branch="main",
        )
        proposed_change.save()
        self._wait_for_guard(client_sync, proposed_change.id, RAISE_SILVER)

        conclusion, messages = self._guard(client_sync, RAISE_SILVER)
        OPEN_CHECKS[f"Gold outage guard on {RAISE_SILVER}"] = f"{conclusion}: {messages.strip()!r}"

        assert conclusion == "failure"
        assert RAISE_SILVER_MESSAGE in messages

        try:
            response = client_sync.execute_graphql(query=MERGE_MUTATION, variables={"id": proposed_change.id})
            surface = f"mutation returned {response}"
        except GraphQLError as exc:
            surface = f"mutation raised GraphQLError: {exc.errors[0].get('message') if exc.errors else exc}"

        after = client_sync.get(kind=CoreProposedChange, id=proposed_change.id)
        silver_on_main = client_sync.get(kind=ServiceTier, name__value="Silver", branch="main")
        OPEN_CHECKS[f"merge of {RAISE_SILVER}"] = (
            f"{surface}; state after: {after.state.value}; Silver rule on main: {silver_on_main.min_paths.value}"
        )

        assert after.state.value == "open"
        assert silver_on_main.min_paths.value == 0

    def test_moved_plan(self, client_sync: InfrahubClientSync) -> None:
        """With DI-1001 and DI-1002 moved to Paris edge router 2 first, the same maintenance passes the guard.

        The generator moves each gateway to rb02-par01 and does not delete the switch 1 port it released.
        """
        conclusion, messages = self._guard(client_sync, MOVED_NAME)
        OPEN_CHECKS[f"Gold outage guard on {MOVED_NAME}"] = f"{conclusion}: {messages.strip()!r}"
        assert conclusion == "success"
        assert f"{MOVED_NAME} leaves no active Gold service without a path. Gold SLA credit exposure: €0" in messages

        sw01 = client_sync.get(kind=DcimDevice, name__value="sw01-par01", branch=MOVED)
        ports_on = {
            branch: {
                str(port.name.value)
                for port in client_sync.filters(kind=DcimInterfaceL2, device__ids=[sw01.id], branch=branch)
            }
            for branch in ("main", MOVED)
        }
        assert ports_on[MOVED] == ports_on["main"]

        for service_identifier in ("DI-1001", "DI-1002"):
            service = client_sync.get(
                kind=ServiceDedicatedInternet, service_identifier__value=service_identifier, branch=MOVED
            )
            gateways = client_sync.filters(
                kind=DcimInterfaceL3, service__ids=[service.id], branch=MOVED, prefetch_relationships=True
            )
            ports = client_sync.filters(
                kind=DcimInterfaceL2, service__ids=[service.id], branch=MOVED, prefetch_relationships=True
            )
            assert [gateway.device.peer.name.value for gateway in gateways] == ["rb02-par01"]
            assert [port.device.peer.name.value for port in ports] == ["sw02-par01"]

        result = build_blast_radius(_q1(client_sync, MOVED), _q1(client_sync, "main"))
        assert result.headline == "2 services have no other path during this change, and none of them is Gold"
        assert _tiles(result) == {
            "Customers affected": "2",
            "Gold services affected": "0 of 5",
            "Gold SLA credit exposure, per month": "€0",
        }
        assert [row.service for row in result.affected_rows] == ["DI-1004", "DI-1006"]

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

    def test_tier_rules_in_the_query(self, client_sync: InfrahubClientSync) -> None:
        """The query's `ServiceTier` block reads each tier's minimum separate paths: Gold 1, Silver 0, Bronze 0."""
        rules = tier_rules(_q1(client_sync, "main"))
        OPEN_CHECKS["min_paths read from the ServiceTier block"] = str(rules)
        assert rules == {"Gold": 1, "Silver": 0, "Bronze": 0}

    def test_blast_radius_paris(self, client_sync: InfrahubClientSync) -> None:
        # The guard's path traversal with the network kinds finds the interface path only: DI-1001 reaches
        # Paris edge router 1, DI-1003 (on router 2, same site) does not reach it through the site.
        router = client_sync.get(kind=DcimDevice, name__value="rb01-par01", branch=PARIS)
        for service_identifier, expected in (("DI-1001", 1), ("DI-1003", 0)):
            service = client_sync.get(
                kind=ServiceDedicatedInternet, service_identifier__value=service_identifier, branch=PARIS
            )
            paths = client_sync.traverse_paths(
                service, router, kind_filter=list(NETWORK_KINDS), max_depth=MAX_HOPS, branch=PARIS
            )
            assert paths.count == expected, service_identifier

        result = build_blast_radius(_q1(client_sync, PARIS), _q1(client_sync, "main"))

        assert result.headline == "2 Gold services for Northbank have no other path during this change"
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

        assert result.headline == "1 Gold service for Helix Health has no other path during this change"
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

    def test_moved_plan_merges(self, client_sync: InfrahubClientSync) -> None:
        """The plan with the Gold services moved first merges. Runs last: the merge changes main."""
        proposed_change = client_sync.get(kind=CoreProposedChange, name__value=MOVED_NAME)
        client_sync.execute_graphql(query=MERGE_MUTATION, variables={"id": proposed_change.id})

        after = client_sync.get(kind=CoreProposedChange, id=proposed_change.id)
        router = client_sync.get(kind=DcimDevice, name__value="rb01-par01", branch="main")
        OPEN_CHECKS[f"merge of {MOVED_NAME}"] = (
            f"state after: {after.state.value}; rb01-par01 on main: {router.status.value}"
        )

        assert after.state.value == "merged"
        assert router.status.value == "maintenance"

        # The generator runs on main after the merge. It must leave the freed switch 1 ports in place:
        # the ports belong to the switch, not to the generator's tracking group.
        sw01 = client_sync.get(kind=DcimDevice, name__value="sw01-par01", branch="main")
        wait_until_ports = [
            str(port.name.value)
            for port in client_sync.filters(kind=DcimInterfaceL2, device__ids=[sw01.id], branch="main")
        ]
        OPEN_CHECKS["switch 1 ports on main after the merge"] = ", ".join(sorted(wait_until_ports))
        assert {"Ethernet4", "Ethernet5"} <= set(wait_until_ports)

    def test_report_open_checks(self) -> None:
        print("\nOpen checks:")
        for check, result in OPEN_CHECKS.items():
            print(f"- {check}: {result}")
        assert OPEN_CHECKS
