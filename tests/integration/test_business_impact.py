"""The business impact demo against a live Infrahub, seeded once: maintenance figures, notification and cost.

The test class runs the storyline in order on one Infrahub stack, which the SDK's test base class starts
before the first test and removes after the last one:

1. Loads the schema and data (including `data/10_customers_tiers.yml`) and imports the repository: the
   stored queries `business_impact_services` and `cost_of_service`, the generator definition, the check
   definition, the transforms and the "Affected customers" and "Cost of service" artifact definitions.
2. Before the seed, the stored query `cost_of_service` runs on main without the circuit schema.
3. Runs the seed steps as `invoke seed` does: the circuit schema and the upstream circuits, the services,
   a generator run for each through `infrahubctl`, the second path of each Paris Gold service, the
   request for the "Cost of service" artifact, the outreach webhook and the maintenance proposed changes.
4. Asserts against the seeded environment:

- Planned maintenance: the stored query on main and on the maintenance branches, with the footprint of
  each active service from Infrahub's path traversal, feeds `blast_radius.py`.
- Gold outage guard: its validator passes on the Paris and New York proposed changes and fails on
  Brussels with the message the docs show, it fails on a proposed change that deletes Brussels edge
  router 1, it fails on a proposed change that raises the Silver rule to 2 separate paths, and Infrahub
  refuses to merge the Brussels proposed change and the Silver rule change. No guard message and no
  figure names money. The stack runs the stock Infrahub image, where `service_catalog` is not
  installed, so the guard's messages also record that the task worker imports
  `service_catalog.business_impact` from the repository.
- Customer notification: the `gold-outreach` webhook exists, inactive, on the creation of a proposed
  change, with the `outreach_payload` transform; the "Affected customers" artifact on the Paris branch,
  read as the Customer notification page reads it, is Ready and lists the four Paris customers with
  their statuses; `OutreachPayload`, run on a creation event in the shape Infrahub 1.11.4 sends, lists
  Northbank and Helix Health for Paris, is blocked for Brussels and lists no customer for New York.
- Cost of service: the seed loads one upstream circuit on the Ethernet4 of each edge router, a second
  run changes nothing, and the Circuit menu item sits under the repository's Device Management menu;
  the "Cost of service" artifact on main has circuit rows and equals the CSV of `cost_lines` from the
  stored query, the circuit query and the footprints, so the download matches the page row for row;
  DI-1001's shares equal the hand calculation; the totals add the unrounded shares and round once, and
  the edge routers that carry no service are listed apart; a change to a circuit's monthly cost leaves
  the stored CSV older than the page's figures, and the page's Regenerate request
  (`infrahub.generate_artifact`) brings it up to date. That change is made on main, so it runs last.

It also records open checks: whether `role__values` works, whether opening a
proposed change reruns the generator, whether `customer` and `tier` survive the
generator runs, whether `requested_by` and `request_reason` survive the generator runs, and whether a
customer named "Equinix" is refused by the name uniqueness that `OrganizationGeneric` shares with providers.
The last test prints them all; run with `-rP` to see it.

Marked `extended`: the proposed change pipelines alone take several minutes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import pytest

from infrahub_sdk.client import InfrahubClient
from infrahub_sdk.exceptions import GraphQLError
from infrahub_sdk.node import InfrahubNode
from infrahub_sdk.protocols import (
    CoreArtifact,
    CoreCheckDefinition,
    CoreCustomWebhook,
    CoreGeneratorInstance,
    CoreProposedChange,
    CoreStandardCheck,
    CoreValidator,
)
from infrahub_sdk.testing.docker import TestInfrahubDockerClient
from infrahub_sdk.testing.repository import GitRepo
from service_catalog.business_impact import seed
from service_catalog.business_impact.blast_radius import (
    BlastRadius,
    build_blast_radius,
    parse_devices,
    parse_services,
    paths,
)
from service_catalog.business_impact.change_impact import add_footprints
from service_catalog.business_impact.gold_outage_guard import tier_rules
from service_catalog.business_impact.notification_view import NotificationList, notification_state
from service_catalog.cost_of_service.circuits import add_footprints as add_cost_footprints
from service_catalog.cost_of_service.circuits import read_circuits
from service_catalog.cost_of_service.cost import (
    ONE_TIME,
    PER_MONTH,
    circuits,
    cost_lines,
    has_circuits,
    service_lines,
    shares,
    to_csv,
    totals,
    with_circuits,
)
from service_catalog.cost_of_service.view import csv_is_current
from service_catalog.infrahub import (
    ARTIFACT_READY,
    Generation,
    StoredArtifact,
    generate_artifact,
    read_artifact,
    read_stored_artifact,
    run_query,
)
from service_catalog.protocols_sync import (
    DcimDevice,
    DcimInterface,
    OrganizationCustomer,
    ServiceDedicatedInternet,
    ServiceTier,
)
from tests.unit.builders import BRUSSELS_MESSAGE, RAISE_SILVER, RAISE_SILVER_MESSAGE, tiles
from transforms.outreach_payload import OutreachPayload

from .proposed_changes import open_change, try_merge

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from infrahub_sdk.client import InfrahubClientSync
    from infrahub_sdk.spec.object import ObjectFile
    from infrahub_sdk.yaml import SchemaFile

pytestmark = pytest.mark.extended

logger = logging.getLogger(__name__)

QUERY_NAME = "business_impact_services"
PARIS = "maint-rb01-par01"
BRUSSELS = "maint-sw01-bru01"
DELETED = "delete-rb01-bru01"
DELETED_NAME = "Delete Brussels router 1"
DELETED_MESSAGE = (
    "Delete Brussels router 1 leaves 1 Gold service for Helix Health with no other path (DI-2001). "
    "It has 1 separate path on the current network and 0 during this change. "
)
PARIS_GOLD = ("DI-1001", "DI-1002", "DI-1003")
GOLD_RULE_SENTENCE = "Gold requires at least 1 separate path during a change, and this change leaves 0."
MONEY_WORDS = ("EUR", "€", "SLA", "credit", "contract value", "charge")
RAISED = "raise-silver-rule"

# Open-check results, filled by the tests and printed by the last one.
OPEN_CHECKS: dict[str, str] = {}


def _q1(client_sync: InfrahubClientSync, branch: str) -> dict[str, Any]:
    """The stored query on `branch` with the footprint of each active service, as the pages read it."""
    data: dict[str, Any] = run_query(name=QUERY_NAME, branch=branch, client=client_sync)
    traced: dict[str, Any] = asyncio.run(add_footprints(InfrahubClient(config=client_sync.config), data, branch))
    return traced


def _business_fields(data: dict[str, Any]) -> dict[str, tuple[str | None, str | None]]:
    """Customer and tier per service identifier, as the query reads them."""
    fields = {}
    for edge in data["ServiceDedicatedInternet"]["edges"]:
        node = edge["node"]
        customer = (node["customer"] or {}).get("node") or {}
        tier = (node["tier"] or {}).get("node") or {}
        fields[node["service_identifier"]["value"]] = (
            (customer.get("name") or {}).get("value"),
            (tier.get("name") or {}).get("value"),
        )
    return fields


EXPECTED_FIELDS = {row.service_identifier: (row.customer, row.tier) for row in seed.SEED_SERVICES}


def _assert_fields_survive(client_sync: InfrahubClientSync, branch: str) -> None:
    fields = _business_fields(_q1(client_sync, branch))
    seeded = {identifier: fields.get(identifier) for identifier in EXPECTED_FIELDS}
    OPEN_CHECKS[f"customer and tier survive on {branch}"] = str(seeded == EXPECTED_FIELDS)
    assert seeded == EXPECTED_FIELDS
    _assert_request_record_survives(client_sync, branch)


EXPECTED_REQUEST_RECORDS = {
    row.service_identifier: (row.requested_by, row.request_reason) for row in seed.SEED_SERVICES
}


def _assert_request_record_survives(client_sync: InfrahubClientSync, branch: str) -> None:
    """The request record of each seeded service, read with the SDK because the stored query does not return it."""
    records = {
        str(service.service_identifier.value): (service.requested_by.value, service.request_reason.value)
        for service in client_sync.all(kind=ServiceDedicatedInternet, branch=branch)
    }
    seeded = {identifier: records.get(identifier) for identifier in EXPECTED_REQUEST_RECORDS}
    OPEN_CHECKS[f"requested_by and request_reason survive on {branch}"] = str(seeded == EXPECTED_REQUEST_RECORDS)
    assert seeded == EXPECTED_REQUEST_RECORDS


def _rows(result: BlastRadius) -> dict[str, tuple[str, str, int, int, str]]:
    """Customer, tier, paths on main, paths during the change and status per affected service."""
    return {
        row.service: (row.customer, row.tier, row.paths_on_main, row.paths_during_change, row.status)
        for row in result.affected_rows
    }


NOTIFICATION_ARTIFACT = "affected-customers"
ARTIFACT_TIMEOUT_S = 300.0

PARIS_ARTIFACT = [
    {"customer": "Helix Health", "tier": "Gold", "services": ["DI-1003"], "status": "at risk, notified"},
    {"customer": "Northbank", "tier": "Gold", "services": ["DI-1001", "DI-1002"], "status": "at risk, notified"},
    {"customer": "Maison Verte", "tier": "Silver", "services": ["DI-1004"], "status": "down, not notified"},
    {"customer": "Rapid Freight", "tier": "Bronze", "services": ["DI-1006"], "status": "down, not notified"},
]


def _creation_event(change: Any) -> dict[str, Any]:  # noqa: ANN401 - an SDK node
    """The data Infrahub 1.11.4 hands a webhook transform when a proposed change is created."""

    def attribute(name: str, kind: str, value: object) -> dict[str, object]:
        return {"kind": kind, "name": name, "value": value, "value_previous": None, "value_update_status": "added"}

    attributes = {
        "name": attribute("name", "Text", change.name.value),
        "state": attribute("state", "Text", "open"),
        "is_draft": attribute("is_draft", "Boolean", False),
        "source_branch": attribute("source_branch", "Text", change.source_branch.value),
        "destination_branch": attribute("destination_branch", "Text", "main"),
    }
    return {
        "data": {
            "data": {
                "kind": "CoreProposedChange",
                "action": "created",
                "fields": list(attributes),
                "node_id": change.id,
                "changelog": {
                    "node_id": change.id,
                    "node_kind": "CoreProposedChange",
                    "attributes": attributes,
                    "display_label": change.name.value,
                    "relationships": {},
                },
            },
            "id": "event-id",
            "branch": "main",
            "account_id": "account-id",
            "occured_at": "2026-10-12 10:23:13.715026+00:00",
            "event": "infrahub.node.created",
        }
    }


def circuit_ids(data: dict[str, Any]) -> list[str]:
    """The circuit ID of each edge router that has one."""
    return sorted(circuit.circuit_id for circuit in circuits(data).values())


COST_QUERY_NAME = "cost_of_service"
COST_ARTIFACT = "cost-of-service"


def _cost_stored_query(client: InfrahubClientSync) -> dict[str, Any]:
    data: dict[str, Any] = run_query(COST_QUERY_NAME, branch="main", client=client)
    return data


def _cost_query(client: InfrahubClientSync) -> dict[str, Any]:
    """The stored query merged with the circuit query, with the footprint of each active service, as the page
    reads them."""
    stored = _cost_stored_query(client)

    async def read() -> dict[str, Any]:
        async_client = InfrahubClient(config=client.config)
        merged = with_circuits(stored, await read_circuits(async_client, "main"))
        return await add_cost_footprints(async_client, merged, "main")

    return asyncio.run(read())


CIRCUIT_LANDING_QUERY = """
query {
  DcimCircuitEndpoint {
    edges {
      node {
        circuit { node { circuit_id { value } monthly_cost { value } } }
        connected_endpoint {
          node {
            ... on DcimInterface {
              name { value }
              status { value }
              role { value }
              device { node { name { value } } }
            }
          }
        }
      }
    }
  }
}
"""


CIRCUIT_MENU_QUERY = """
query {
  CoreMenuItem(namespace__value: "Dcim", name__value: "Circuit") {
    edges { node { kind { value } parent { node { name { value } } } } }
  }
}
"""


class TestBusinessImpact(TestInfrahubDockerClient):  # noqa: PLR0904 - one test per step of the storyline
    # Load, import and describe the repository

    @pytest.fixture(scope="class")
    def default_branch(self) -> str:
        return "main"

    @pytest.fixture(scope="class")
    def address(self, infrahub_port: int) -> str:
        return f"http://localhost:{infrahub_port}"

    def test_schema_load(
        self, client_sync: InfrahubClientSync, repository_schemas: list[SchemaFile], default_branch: str
    ) -> None:
        client_sync.schema.load(schemas=[item.content for item in repository_schemas])
        client_sync.schema.wait_until_converged(branch=default_branch)

    async def test_data_load(
        self, client: InfrahubClient, repository_object_files: list[ObjectFile], default_branch: str
    ) -> None:
        await client.schema.all()
        object_files = repository_object_files
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
        # The check runs the Planned maintenance page's stored query: Infrahub links it from `GoldOutageGuard.query`.
        guard = client_sync.get(kind=CoreCheckDefinition, name__value="gold_outage_guard", prefetch_relationships=True)
        assert guard.query.peer.name.value == QUERY_NAME

    def test_repository_items_are_described(self, client_sync: InfrahubClientSync) -> None:
        """The seed sets the description of the check, the generator, the artifact definitions and the queries."""
        seed.wait_for_repository(client_sync)
        seed.describe_repository_items(client_sync)
        seed.describe_repository_items(client_sync)

        for (kind, name), description in seed.REPOSITORY_DESCRIPTIONS.items():
            node = client_sync.get(kind=kind, name__value=name)
            assert node.description.value == description, name

    def _runner(self, address: str) -> Callable[[str], None]:
        """Run an `infrahubctl` command against the test server; raise `SeedError` when it exits non-zero."""

        def run(command: str) -> None:
            result = self.execute_command(command=command, address=address)
            if result.returncode != 0:
                raise seed.SeedError(f"exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")

        return run

    # Before the seed: the cost query without the circuit schema, then the circuits

    def test_query_runs_without_the_circuit_schema(self, client_sync: InfrahubClientSync) -> None:
        """The repository import loads the stored query without the circuit schema, and the query runs."""
        seed.wait_for_repository(client_sync)
        assert "DcimCircuit" not in client_sync.schema.all(branch="main", refresh=True)
        data = _cost_stored_query(client_sync)

        routers = [edge for edge in data["DcimDevice"]["edges"] if edge["node"]["role"]["value"] == "edge"]
        assert len(data["DcimDevice"]["edges"]) == 16
        assert len(routers) == 8
        assert not [
            interface
            for router in routers
            for interface in router["node"]["upstream"]["edges"]
            if (interface["node"].get("connected_endpoint") or {}).get("node")
        ]
        assert not has_circuits(_cost_query(client_sync))

    def test_seed_loads_the_upstream_circuits_on_ethernet4(self, client_sync: InfrahubClientSync, address: str) -> None:
        """Each edge router carries one upstream circuit on Ethernet4, and that interface is active; twice."""
        seed.load_upstream_circuits(client_sync, self._runner(address))
        seed.load_upstream_circuits(client_sync, self._runner(address))

        response = client_sync.execute_graphql(query=CIRCUIT_LANDING_QUERY, branch_name="main")
        landed: dict[str, tuple[str, str, str, int]] = {}
        for edge in response["DcimCircuitEndpoint"]["edges"]:
            node = edge["node"]
            interface = node["connected_endpoint"]["node"]
            landed[interface["device"]["node"]["name"]["value"]] = (
                interface["name"]["value"],
                interface["status"]["value"],
                interface["role"]["value"],
                node["circuit"]["node"]["monthly_cost"]["value"],
            )
        sites = {"par01": 2500, "bru01": 2000, "nyc01": 3000, "dal01": 3000}
        assert landed == {
            f"rb0{index}-{site}": ("Ethernet4", "active", "upstream", cost)
            for site, cost in sites.items()
            for index in (1, 2)
        }
        # The circuit file updates the interfaces the router template created, it adds none.
        ethernet4 = client_sync.filters(kind=DcimInterface, name__value="Ethernet4", branch="main")
        assert len(ethernet4) == 16  # 8 switches and 8 edge routers
        assert len(circuit_ids(_cost_query(client_sync))) == 8

    def test_seed_adds_the_circuit_menu_item_under_device_management(self, client_sync: InfrahubClientSync) -> None:
        """The menu item for DcimCircuit comes with the circuit schema, under the repository's Device Management."""
        response = client_sync.execute_graphql(query=CIRCUIT_MENU_QUERY, branch_name="main")
        items = response["CoreMenuItem"]["edges"]

        assert len(items) == 1
        item = items[0]["node"]
        assert item["kind"]["value"] == "DcimCircuit"
        assert item["parent"]["node"]["name"]["value"] == "DeviceManagementMenu"

    # The seed

    def test_seed_services_and_generators(self, client_sync: InfrahubClientSync, address: str) -> None:
        """The seed steps after the circuits, in the order `invoke seed` runs them, up to the second paths."""
        seed.seed_services(client_sync)
        seed.run_generators(client_sync, self._runner(address))
        seed.add_second_paths(client_sync)
        _assert_fields_survive(client_sync, "main")

    def test_second_paths_present_after_seed(self, client_sync: InfrahubClientSync) -> None:
        """Each Paris Gold service has a port on both Paris switches and a gateway on both Paris edge routers."""
        services = {service.identifier: service for service in parse_services(_q1(client_sync, "main"))}
        for identifier in PARIS_GOLD:
            service = services[identifier]
            pairs = sorted((path.switch.name, path.edge_router.name) for path in paths(service))
            assert pairs == [("sw01-par01", "rb01-par01"), ("sw02-par01", "rb02-par01")], identifier
        # The other seeded services keep one path, the Brussels Gold services included.
        others = [row.service_identifier for row in seed.SEED_SERVICES if row.service_identifier not in PARIS_GOLD]
        assert {identifier: len(paths(services[identifier])) for identifier in others} == dict.fromkeys(others, 1)

    def test_second_paths_are_not_added_twice(self, client_sync: InfrahubClientSync) -> None:
        """A second run of the step leaves two paths per Paris Gold service."""
        seed.add_second_paths(client_sync)
        services = {service.identifier: service for service in parse_services(_q1(client_sync, "main"))}
        assert [len(paths(services[identifier])) for identifier in PARIS_GOLD] == [2, 2, 2]

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
        """The last seed steps, in the order `invoke seed` runs them: the cost of service artifact request, the
        outreach webhook, the maintenance proposed changes and the wait for the artifact."""
        main_instances = len(client_sync.all(kind=CoreGeneratorInstance, branch="main"))
        cost_request = seed.request_cost_of_service(client_sync)
        seed.ensure_outreach_webhook(client_sync)
        seed.seed_maintenance(client_sync)
        seed.wait_for_cost_of_service(client_sync, cost_request)

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

    # Gold outage guard

    def _guard(self, client_sync: InfrahubClientSync, name: str) -> tuple[str | None, str]:
        """Conclusion of the Gold outage guard validator on a proposed change, and its check messages.

        The check breaks each message into short lines, so the line breaks become spaces here.
        """
        proposed_change = client_sync.get(kind=CoreProposedChange, name__value=name)
        validators = client_sync.filters(kind=CoreValidator, proposed_change__ids=[proposed_change.id])
        guard = [validator for validator in validators if validator.label.value == seed.GUARD_VALIDATOR_LABEL]
        assert len(guard) == 1, f"{name}: validators {[validator.label.value for validator in validators]}"
        checks = client_sync.filters(kind=CoreStandardCheck, validator__ids=[guard[0].id])
        messages = " ".join(str(check.message.value or "") for check in checks)
        return guard[0].conclusion.value, messages.replace("\n", " ")

    def test_gold_outage_guard_passes_on_paris(self, client_sync: InfrahubClientSync) -> None:
        """Each Paris Gold service keeps its second path while Paris edge router 1 is in maintenance."""
        conclusion, messages = self._guard(client_sync, "Paris router 1 maintenance")
        OPEN_CHECKS["Gold outage guard on Paris router 1 maintenance"] = f"{conclusion}: {messages.strip()!r}"

        assert conclusion == "success"
        assert "Paris router 1 maintenance leaves every active Gold service with at least 1 separate path." in messages
        assert not [word for word in MONEY_WORDS if word in messages]

    def test_gold_outage_guard_fails_on_brussels(self, client_sync: InfrahubClientSync) -> None:
        """The guard fails with the message the docs show: Helix Health, Gold, DI-2001, 1 path then 0."""
        conclusion, messages = self._guard(client_sync, "Brussels switch 1 maintenance")
        OPEN_CHECKS["Gold outage guard on Brussels switch 1 maintenance"] = f"{conclusion}: {messages.strip()!r}"

        assert conclusion == "failure"
        assert BRUSSELS_MESSAGE in messages
        assert GOLD_RULE_SENTENCE in messages
        assert not [word for word in MONEY_WORDS if word in messages]
        # The rule lives in service_catalog.business_impact, so its message proves the worker imported it.
        OPEN_CHECKS["task worker imports service_catalog.business_impact (stock image)"] = "True"

    def test_gold_outage_guard_passes_on_new_york(self, client_sync: InfrahubClientSync) -> None:
        """No active service runs through `rb01-nyc01`."""
        conclusion, messages = self._guard(client_sync, "New York router 1 maintenance")
        OPEN_CHECKS["Gold outage guard on New York router 1 maintenance"] = f"{conclusion}: {messages.strip()!r}"

        assert conclusion == "success"
        assert "Check succesfully completed" in messages
        assert (
            "New York router 1 maintenance leaves every active Gold service with at least 1 separate path." in messages
        )

    def test_gold_outage_guard_fails_when_a_device_is_deleted(self, client_sync: InfrahubClientSync) -> None:
        """Deleting Brussels edge router 1 removes DI-2001's gateway with it: no device is left with a status
        to check, and the guard still fails because DI-2001 has no edge router on the branch.
        """
        client_sync.branch.create(branch_name=DELETED, sync_with_git=False, description=DELETED_NAME)
        router = client_sync.get(kind=DcimDevice, name__value="rb01-bru01", branch=DELETED)
        router.delete()

        open_change(client_sync, DELETED, DELETED_NAME)

        conclusion, messages = self._guard(client_sync, DELETED_NAME)
        OPEN_CHECKS[f"Gold outage guard on {DELETED_NAME}"] = f"{conclusion}: {messages.strip()!r}"

        assert conclusion == "failure"
        assert DELETED_MESSAGE in messages
        assert GOLD_RULE_SENTENCE in messages
        assert not [word for word in MONEY_WORDS if word in messages]

    def test_tightening_a_tier_rule_fails(self, client_sync: InfrahubClientSync) -> None:
        """Raising the Silver rule from 0 to 2 fails, because each active Silver service has 1 path, and
        Infrahub refuses to merge the proposed change.
        """
        client_sync.branch.create(branch_name=RAISED, sync_with_git=False, description=RAISE_SILVER)
        silver = client_sync.get(kind=ServiceTier, name__value="Silver", branch=RAISED)
        silver.min_paths.value = 2
        silver.save()

        proposed_change = open_change(client_sync, RAISED, RAISE_SILVER)

        conclusion, messages = self._guard(client_sync, RAISE_SILVER)
        OPEN_CHECKS[f"Gold outage guard on {RAISE_SILVER}"] = f"{conclusion}: {messages.strip()!r}"

        assert conclusion == "failure"
        assert RAISE_SILVER_MESSAGE in messages

        surface = try_merge(client_sync, proposed_change.id)

        after = client_sync.get(kind=CoreProposedChange, id=proposed_change.id)
        silver_on_main = client_sync.get(kind=ServiceTier, name__value="Silver", branch="main")
        OPEN_CHECKS[f"merge of {RAISE_SILVER}"] = (
            f"{surface}; state after: {after.state.value}; Silver rule on main: {silver_on_main.min_paths.value}"
        )

        assert after.state.value == "open"
        assert silver_on_main.min_paths.value == 0

    def test_merge_refused_on_brussels(self, client_sync: InfrahubClientSync) -> None:
        """Infrahub refuses to merge a proposed change whose guard failed."""
        proposed_change = client_sync.get(kind=CoreProposedChange, name__value="Brussels switch 1 maintenance")
        # Infrahub refuses a merge when any validator other than data integrity did not succeed, so first show
        # that the Gold outage guard is the only one that failed: the refusal is then the guard's.
        validators = client_sync.filters(kind=CoreValidator, proposed_change__ids=[proposed_change.id])
        conclusions = {str(validator.label.value): validator.conclusion.value for validator in validators}
        OPEN_CHECKS["validator conclusions on Brussels switch 1 maintenance"] = str(conclusions)
        failing = sorted(
            label for label, conclusion in conclusions.items() if conclusion != "success" and label != "Data Integrity"
        )
        assert failing == [seed.GUARD_VALIDATOR_LABEL]
        surface = try_merge(client_sync, proposed_change.id)

        after = client_sync.get(kind=CoreProposedChange, id=proposed_change.id)
        switch = client_sync.get(kind=DcimDevice, name__value="sw01-bru01", branch="main")
        OPEN_CHECKS["merge of Brussels switch 1 maintenance"] = (
            f"{surface}; state after: {after.state.value}; sw01-bru01 on main: {switch.status.value}"
        )

        assert after.state.value == "open"
        assert switch.status.value == "active"

    # Customer notification

    def test_outreach_webhook_is_seeded_inactive(self, client_sync: InfrahubClientSync) -> None:
        webhook = client_sync.get(kind=CoreCustomWebhook, name__value="gold-outreach", prefetch_relationships=True)

        assert webhook.event_type.value == "infrahub.node.created"
        assert webhook.node_kind.value == "CoreProposedChange"
        assert webhook.branch_scope.value == "default_branch"
        assert webhook.url.value == "https://crm.example.com/api/campaigns"
        assert webhook.active.value is False
        assert webhook.transformation.peer.name.value == "outreach_payload"

    def test_outreach_webhook_is_not_created_twice(self, client_sync: InfrahubClientSync) -> None:
        seed.ensure_outreach_webhook(client_sync)

        assert len(client_sync.filters(kind=CoreCustomWebhook, name__value="gold-outreach")) == 1

    def test_affected_customers_artifact_on_paris(self, client_sync: InfrahubClientSync) -> None:
        """The artifact on the Paris branch is Ready and lists the four Paris customers with their statuses.

        The page shows it as a list, not as a notice, because its `branch` field names the Paris branch.
        """
        stored: StoredArtifact | None = None
        deadline = time.monotonic() + ARTIFACT_TIMEOUT_S
        while time.monotonic() < deadline:
            stored = read_stored_artifact(NOTIFICATION_ARTIFACT, branch=PARIS, client=client_sync)
            if stored is not None and stored.content and json.loads(stored.content).get("customers"):
                break
            time.sleep(seed.POLL_INTERVAL_S)

        assert stored is not None
        assert stored.status == ARTIFACT_READY
        assert stored.content is not None
        assert json.loads(stored.content) == {"branch": PARIS, "blocked": False, "customers": PARIS_ARTIFACT}
        assert isinstance(notification_state(stored.content, PARIS), NotificationList)

    async def _payload(self, client: InfrahubClient, name: str) -> dict[str, Any]:
        change = await client.get(kind=CoreProposedChange, name__value=name, branch="main")
        transform = OutreachPayload(client=client, infrahub_node=InfrahubNode, branch="main")
        payload: dict[str, Any] = await transform.run(data=_creation_event(change))
        assert payload["proposed_change"] == {
            "id": change.id,
            "name": name,
            "source_branch": change.source_branch.value,
        }
        return payload

    async def test_outreach_payload_for_paris(self, client: InfrahubClient) -> None:
        """Northbank and Helix Health, both Gold, and no Silver or Bronze customer."""
        payload = await self._payload(client, "Paris router 1 maintenance")

        assert payload["source"] == "infrahub"
        assert payload["blocked"] is False
        assert payload["customers"] == [
            {"customer": "Helix Health", "tier": "Gold", "services": ["DI-1003"]},
            {"customer": "Northbank", "tier": "Gold", "services": ["DI-1001", "DI-1002"]},
        ]

    @pytest.mark.parametrize(
        ("name", "blocked"),
        [("Brussels switch 1 maintenance", True), ("New York router 1 maintenance", False)],
        ids=["brussels-blocked", "new-york-empty"],
    )
    async def test_outreach_payload_with_no_customer(self, client: InfrahubClient, name: str, *, blocked: bool) -> None:
        payload = await self._payload(client, name)

        assert payload["blocked"] is blocked
        assert payload["customers"] == []

    # Planned maintenance figures

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
        result = build_blast_radius(_q1(client_sync, PARIS), _q1(client_sync, "main"))

        assert result.headline == (
            "3 Gold services for Helix Health and Northbank have fewer separate paths during this change"
        )
        assert tiles(result) == {"Customers affected": "4", "Gold services at risk": "3", "Services down": "2"}
        assert _rows(result) == {
            "DI-1001": ("Northbank", "Gold", 2, 1, "at risk"),
            "DI-1002": ("Northbank", "Gold", 2, 1, "at risk"),
            "DI-1003": ("Helix Health", "Gold", 2, 1, "at risk"),
            "DI-1004": ("Maison Verte", "Silver", 1, 0, "down"),
            "DI-1006": ("Rapid Freight", "Bronze", 1, 0, "down"),
        }

    def test_blast_radius_brussels(self, client_sync: InfrahubClientSync) -> None:
        result = build_blast_radius(_q1(client_sync, BRUSSELS), _q1(client_sync, "main"))

        assert result.headline == "1 Gold service for Helix Health has no path during this change"
        assert tiles(result) == {"Customers affected": "3", "Gold services at risk": "0", "Services down": "3"}
        assert _rows(result)["DI-2001"] == ("Helix Health", "Gold", 1, 0, "down")

    def test_blast_radius_main(self, client_sync: InfrahubClientSync) -> None:
        main = _q1(client_sync, "main")
        result = build_blast_radius(main, main)

        assert result.headline == "No service is affected"
        assert tiles(result) == {"Customers affected": "0", "Gold services at risk": "0", "Services down": "0"}

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

    # Cost of service

    def test_artifact_rows_equal_the_cost_lines(self, client_sync: InfrahubClientSync) -> None:
        """The CSV the page offers for download is the CSV of the lines the page shows."""
        artifacts = client_sync.filters(kind=CoreArtifact, name__value=COST_ARTIFACT, branch="main")
        stored = [artifact for artifact in artifacts if artifact.storage_id.value]
        assert len(stored) == 1
        assert stored[0].content_type.value == "text/csv"
        content: str | None = read_artifact(COST_ARTIFACT, branch="main", client=client_sync)
        assert content is not None

        lines = cost_lines(_cost_query(client_sync))
        assert content == to_csv(lines)
        assert [line for line in lines if line.part == "circuit"]
        header, first = content.splitlines()[:2]
        assert header.split(",")[8] == "method"
        assert first.split(",")[8] == "per active interface"
        # Ten Paris paths and five Brussels paths, three parts each.
        assert len(lines) == 3 * 15
        assert not [line for line in lines if line.note]

    def test_di_1001_by_hand(self, client_sync: InfrahubClientSync) -> None:
        """List price / active interfaces per device, and 2500 x 10000 / 13100 per circuit."""
        lines = service_lines(cost_lines(_cost_query(client_sync)), "DI-1001")
        circuit_share = 2500 * 10000 / (10000 + 1000 + 1000 + 100 + 1000)

        assert [(line.path, line.item, line.input, line.divisor, line.share, line.unit) for line in lines] == [
            ("primary (sw01-par01 / rb01-par01)", "sw01-par01", 6000, 5, 1200.0, ONE_TIME),
            ("primary (sw01-par01 / rb01-par01)", "rb01-par01", 12000, 6, 2000.0, ONE_TIME),
            ("primary (sw01-par01 / rb01-par01)", "COG-PAR-TR-1001", 2500, 13100, circuit_share, PER_MONTH),
            ("backup (sw02-par01 / rb02-par01)", "sw02-par01", 6000, 5, 1200.0, ONE_TIME),
            ("backup (sw02-par01 / rb02-par01)", "rb02-par01", 12000, 6, 2000.0, ONE_TIME),
            ("backup (sw02-par01 / rb02-par01)", "COLT-PAR-TR-2001", 2500, 13100, circuit_share, PER_MONTH),
        ]
        summed = shares(lines)
        # Each sum adds the unrounded shares and rounds once.
        assert (summed.hardware, summed.circuit) == (6400.0, 3816.79)

    def test_totals_round_once(self, client_sync: InfrahubClientSync) -> None:
        """The circuits of the Paris and Brussels edge routers, 2 x 2500 + 2 x 2000, split without losing a cent."""
        data = _cost_query(client_sync)
        summed = shares(cost_lines(data))
        result = totals(data)

        assert (summed.hardware, summed.circuit) == (61000.0, 9000.0)
        assert result.upstream_total == pytest.approx(11000)
        assert [router.router for router in result.unused_routers] == [
            "rb01-dal01",
            "rb01-nyc01",
            "rb02-dal01",
            "rb02-nyc01",
        ]
        assert result.unused_total == pytest.approx(48000)
        # The circuits of the four edge routers with no service are not carried by any service.
        assert result.not_carried_monthly == pytest.approx(4 * 3000)

    def test_regenerate_brings_the_csv_up_to_date_after_a_circuit_change(self, client_sync: InfrahubClientSync) -> None:
        """Infrahub does not regenerate the CSV when a circuit changes; the page's request does. Runs last."""
        circuit = client_sync.get(kind="DcimCircuit", circuit_id__value="COG-PAR-TR-1001", branch="main")
        circuit.monthly_cost.value = 2600
        circuit.save()

        stored: str | None = read_artifact(COST_ARTIFACT, branch="main", client=client_sync)
        assert stored is not None
        assert not csv_is_current(stored, cost_lines(_cost_query(client_sync)))

        outcome: Generation = generate_artifact(COST_ARTIFACT, branch="main", timeout_s=120, client=client_sync)

        assert outcome == Generation.READY
        stored = read_artifact(COST_ARTIFACT, branch="main", client=client_sync)
        assert stored is not None
        assert csv_is_current(stored, cost_lines(_cost_query(client_sync)))

    def test_report_open_checks(self) -> None:
        print("\nOpen checks:")
        for check, result in OPEN_CHECKS.items():
            print(f"- {check}: {result}")
        assert OPEN_CHECKS
