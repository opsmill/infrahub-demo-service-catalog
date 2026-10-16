"""Seed task for the business impact demo.

`invoke seed` calls `run_all`, which runs the step functions in order. The step numbers in the
error messages match the steps the installation guide lists:

1. `wait_for_repository`: wait until the repository import has loaded the
   tiers, customers, stored query and generator definition, and until the
   repository is in sync (`wait_for_repository_in_sync` imports the last
   commit again when an import failed).
   `describe_repository_items`: set the description that the Infrahub web
   interface shows for the check, the generator, the artifact definitions and
   the stored queries, which `.infrahub.yml` cannot describe.
   `load_upstream_circuits`: load the circuit schema, which `.infrahub.yml`
   leaves optional, wait again until the repository is in sync, and load the
   upstream circuit of each edge router that the cost of service reads.
2. `seed_services`: create each of the twelve services on main when it is
   missing, and pin its switch by linking one free customer port.
   `run_generators`: run the provisioning generator for each service on main,
   then check that the service has its port, gateway and VLAN.
   `add_second_paths`: give the three Paris Gold services a second path, a
   port on the other switch and a gateway interface on the other edge router.
   `request_cost_of_service`: ask Infrahub to regenerate the "Cost of service"
   artifact on main. `wait_for_cost_of_service` waits for it after the last
   step, so the generation runs while the maintenance changes are opened.
   `ensure_outreach_webhook`: create the inactive `gold-outreach` webhook,
   before the proposed changes, so the demo shows which change would notify
   the CRM.
3-4. `seed_maintenance`: create or rebase the three maintenance branches, set
   the device to maintenance on each, open the proposed changes and wait for
   their pipelines. The Gold outage guard is expected to pass on the Paris
   and New York changes and to fail on the Brussels change; the wait reports
   each as an expected result.

The pure helpers (port choice, allocation check, validator wait decision) take
plain values so they are unit-tested without a server. The client is built by
`build_client`, never at import time.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from infrahub_sdk import InfrahubClientSync
from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError
from infrahub_sdk.protocols import (
    CoreArtifactDefinition,
    CoreCheckDefinition,
    CoreCustomWebhook,
    CoreGeneratorDefinition,
    CoreGenericRepository,
    CoreGraphQLQuery,
    CoreProposedChange,
    CoreTransformPython,
    CoreValidator,
)
from service_catalog.infrahub import read_artifact
from service_catalog.network import CORE_ROLE, EDGE_ROLE
from service_catalog.protocols_sync import (
    DcimDevice,
    DcimInterface,
    DcimInterfaceL2,
    DcimInterfaceL3,
    IpamVLAN,
    OrganizationCustomer,
    ServiceDedicatedInternet,
    ServiceTier,
)

from .blast_radius import MAIN_BRANCH, TIER_ORDER
from .change_impact import QUERY_NAME

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

GENERATOR_NAME = "dedicated_internet_generator"
GENERATOR_GROUP = "automated_dedicated_internet"
CUSTOMER_PORT_ROLE = "customer"
FREE_PORT_STATUS = "free"
MAINTENANCE_STATUS = "maintenance"
OPEN_STATE = "open"
VALIDATOR_COMPLETED = "completed"
VALIDATOR_FAILURE = "failure"
# Infrahub labels a check definition's validator "Check: <definition name>" (git/tasks.py in 1.11.4).
GUARD_VALIDATOR_LABEL = "Check: gold_outage_guard"

POLL_INTERVAL_S = 5.0
# The artifact waits poll every second: Infrahub renders the CSV in a few seconds.
ARTIFACT_POLL_INTERVAL_S = 1.0
REPOSITORY_TIMEOUT_S = 600.0
PIPELINE_TIMEOUT_S = 600.0
ARTIFACT_TIMEOUT_S = 300.0
# When the artifact has not changed this long after the request, the seed posts the request once more.
ARTIFACT_RESEND_S = 60.0

# The circuit schema and the upstream circuits, which `.infrahub.yml` does not load.
CIRCUIT_SCHEMA = "schemas/circuit"
UPSTREAM_CIRCUITS_FILE = "data/business_impact/upstream_circuits.yml"
# The Circuit menu item, loaded only with the circuit schema: a menu item for a missing kind opens a broken list.
CIRCUIT_MENU_FILE = "menu_circuit.yml"
CIRCUIT_KIND = "DcimCircuit"
SCHEMA_WAIT_S = 60

# The "Cost of service" artifact on main.
COST_DEFINITION = "Cost of service"
COST_ARTIFACT = "cost-of-service"

# The outreach webhook: inactive, with a placeholder CRM URL, because the demo runs no CRM.
OUTREACH_TRANSFORM = "outreach_payload"
OUTREACH_WEBHOOK: dict[str, Any] = {
    "name": "gold-outreach",
    "description": (
        "Sends the at-risk Gold customers of a new proposed change to the CRM. Set the CRM URL and activate it."
    ),
    "event_type": "infrahub.node.created",
    "node_kind": "CoreProposedChange",
    "branch_scope": "default_branch",
    "url": "https://crm.example.com/api/campaigns",
    "active": False,
}

# The repository that `bootstrap/repository.yaml` adds, and its sync status.
REPOSITORY_NAME = "infrahub-demo-service-catalog"
REPOSITORY_IN_SYNC = "in-sync"
REPOSITORY_IMPORT_ERROR = "error-import"
# Imports the repository's last commit again.
REIMPORT_MUTATION = """
mutation ReimportRepository($id: String!) {
  InfrahubRepositoryProcess(data: {id: $id}) {
    ok
  }
}
"""
# How many times the seed imports the last commit again after an import error before it stops.
REIMPORT_ATTEMPTS = 2
REIMPORT_START_TIMEOUT_S = 60.0

EXPECTED_TIERS: tuple[str, ...] = TIER_ORDER
EXPECTED_CUSTOMERS: tuple[str, ...] = ("Northbank", "Helix Health", "Maison Verte", "Rapid Freight")


class SeedError(RuntimeError):
    """A seed step failed; the message names the step and the service or branch."""


@dataclass(frozen=True)
class SeedService:
    """One demo service: its identifier, customer, tier, bandwidth, pinned switch and request record.

    The request record says which team at the customer asked for the service and why.
    """

    service_identifier: str
    customer: str
    tier: str
    bandwidth_mbps: int
    switch: str
    edge_router: str
    requested_by: str
    request_reason: str
    ip_package: str = "small"

    @property
    def site(self) -> str:
        """Site shortname, taken from the pinned switch name (`sw01-par01` -> `par01`)."""
        return self.switch.split("-", 1)[1]


@dataclass(frozen=True)
class MaintenanceChange:
    """A maintenance branch, the device it sets to maintenance and its proposed change."""

    branch: str
    device: str
    proposed_change_name: str
    description: str
    # True when the change leaves a Gold service with no path, so the Gold outage guard must fail it.
    guard_blocks: bool


@dataclass
class CostRequest:
    """A request to regenerate the "Cost of service" artifact: the definition and the content before it."""

    definition: Any
    before: str | None
    posted_at: float
    resent: bool = False


@dataclass(frozen=True)
class SecondPath:
    """A second path the seed adds to a service: a port on `switch` and a gateway interface on `edge_router`."""

    service_identifier: str
    switch: str
    edge_router: str


SEED_SERVICES: tuple[SeedService, ...] = (
    SeedService(
        "DI-1001",
        "Northbank",
        "Gold",
        10000,
        "sw01-par01",
        "rb01-par01",
        requested_by="Northbank network operations",
        request_reason="Primary internet access for the Paris trading floor",
    ),
    SeedService(
        "DI-1002",
        "Northbank",
        "Gold",
        1000,
        "sw01-par01",
        "rb01-par01",
        requested_by="Northbank network operations",
        request_reason="Internet access for the Paris back office",
    ),
    SeedService(
        "DI-1003",
        "Helix Health",
        "Gold",
        1000,
        "sw02-par01",
        "rb02-par01",
        requested_by="Helix Health IT infrastructure",
        request_reason="Internet access for the Paris clinic",
    ),
    SeedService(
        "DI-1004",
        "Maison Verte",
        "Silver",
        1000,
        "sw01-par01",
        "rb01-par01",
        requested_by="Maison Verte IT",
        request_reason="Internet access for the Paris flagship store",
    ),
    SeedService(
        "DI-1005",
        "Maison Verte",
        "Silver",
        100,
        "sw02-par01",
        "rb02-par01",
        requested_by="Maison Verte IT",
        request_reason="Internet access for the Paris warehouse",
    ),
    SeedService(
        "DI-1006",
        "Rapid Freight",
        "Bronze",
        100,
        "sw01-par01",
        "rb01-par01",
        requested_by="Rapid Freight logistics IT",
        request_reason="Internet access for the Paris depot",
    ),
    SeedService(
        "DI-1007",
        "Rapid Freight",
        "Bronze",
        1000,
        "sw02-par01",
        "rb02-par01",
        requested_by="Rapid Freight logistics IT",
        request_reason="Internet access for the Paris sorting centre",
    ),
    SeedService(
        "DI-2001",
        "Helix Health",
        "Gold",
        10000,
        "sw01-bru01",
        "rb01-bru01",
        requested_by="Helix Health IT infrastructure",
        request_reason="Primary internet access for the Brussels hospital",
    ),
    SeedService(
        "DI-2002",
        "Northbank",
        "Gold",
        1000,
        "sw02-bru01",
        "rb02-bru01",
        requested_by="Northbank network operations",
        request_reason="Internet access for the Brussels office",
    ),
    SeedService(
        "DI-2003",
        "Maison Verte",
        "Silver",
        1000,
        "sw01-bru01",
        "rb01-bru01",
        requested_by="Maison Verte IT",
        request_reason="Internet access for the Brussels store",
    ),
    SeedService(
        "DI-2004",
        "Rapid Freight",
        "Bronze",
        100,
        "sw02-bru01",
        "rb02-bru01",
        requested_by="Rapid Freight logistics IT",
        request_reason="Internet access for the Brussels depot",
    ),
    SeedService(
        "DI-2005",
        "Rapid Freight",
        "Bronze",
        1000,
        "sw01-bru01",
        "rb01-bru01",
        requested_by="Rapid Freight logistics IT",
        request_reason="Internet access for the Brussels cross-dock",
    ),
)

MAINTENANCE_CHANGES: tuple[MaintenanceChange, ...] = (
    MaintenanceChange(
        branch="maint-rb01-par01",
        device="rb01-par01",
        proposed_change_name="Paris router 1 maintenance",
        description="Maintenance on Paris edge router 1 (rb01-par01)",
        guard_blocks=False,
    ),
    MaintenanceChange(
        branch="maint-sw01-bru01",
        device="sw01-bru01",
        proposed_change_name="Brussels switch 1 maintenance",
        description="Maintenance on Brussels switch 1 (sw01-bru01)",
        guard_blocks=True,
    ),
    MaintenanceChange(
        branch="maint-rb01-nyc01",
        device="rb01-nyc01",
        proposed_change_name="New York router 1 maintenance",
        description="Maintenance on New York edge router 1 (rb01-nyc01)",
        guard_blocks=False,
    ),
)

# The Paris Gold services get a path through the other switch and edge router, so the Paris router 1
# maintenance leaves each of them one path. The Brussels Gold services keep a single path.
SECOND_PATHS: tuple[SecondPath, ...] = (
    SecondPath("DI-1001", "sw02-par01", "rb02-par01"),
    SecondPath("DI-1002", "sw02-par01", "rb02-par01"),
    SecondPath("DI-1003", "sw01-par01", "rb01-par01"),
)
SECOND_PATH_BY_SERVICE: dict[str, SecondPath] = {path.service_identifier: path for path in SECOND_PATHS}


# Plain rows that the pure helpers take


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    role: str | None


@dataclass(frozen=True)
class PortRow:
    id: str
    name: str
    role: str | None
    status: str | None
    service_id: str | None


@dataclass(frozen=True)
class ProposedChangeRow:
    id: str
    name: str
    state: str | None
    source_branch: str


@dataclass(frozen=True)
class ValidatorRow:
    label: str | None
    state: str | None
    conclusion: str | None


# Pure helpers


def _natural_key(name: str) -> tuple[str | int, ...]:
    """Sort key that orders `Ethernet9` before `Ethernet10`."""
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name))


def choose_free_port(ports: Iterable[PortRow]) -> PortRow | None:
    """Return the lowest-named port with role customer, status free and no service, or None."""
    free = [
        port
        for port in ports
        if port.role == CUSTOMER_PORT_ROLE and port.status == FREE_PORT_STATUS and port.service_id is None
    ]
    return min(free, key=lambda port: _natural_key(port.name), default=None)


def _role(devices: Mapping[str, DeviceInfo], device_id: str | None) -> str | None:
    device = devices.get(device_id) if device_id is not None else None
    return device.role if device is not None else None


def has_core_port(linked_device_ids: Iterable[str | None], devices: Mapping[str, DeviceInfo]) -> bool:
    """True when any interface linked to the service sits on a device with role core."""
    return any(_role(devices, device_id) == CORE_ROLE for device_id in linked_device_ids)


def allocation_problems(
    service: SeedService,
    port_device_ids: Sequence[str | None],
    gateway_device_ids: Sequence[str | None],
    vlan_count: int,
    devices: Mapping[str, DeviceInfo],
) -> list[str]:
    """List what the generator did not allocate: one core port on the pinned switch, one edge gateway, one VLAN.

    A service in SECOND_PATHS may also have the port and gateway of its second path, from an earlier seed run.
    """
    problems: list[str] = []
    second = SECOND_PATH_BY_SERVICE.get(service.service_identifier)

    def names(device_ids: Sequence[str | None], role: str) -> list[str]:
        found = (devices.get(device_id) for device_id in device_ids if device_id is not None)
        return [device.name for device in found if device is not None and device.role == role]

    def check(found: list[str], first: str, other: str | None, what: str) -> None:
        allowed = {first} if other is None else {first, other}
        expected = f"one {what}" if other is None else f"one or two {what}s"
        if not found or len(found) != len(set(found)) or len(found) > len(allowed):
            problems.append(f"expected {expected}, found {len(found)}")
        elif first not in found or not set(found) <= allowed:
            extra = "" if other is None else f", and optionally {other}"
            problems.append(f"{what} on {', '.join(sorted(found))}, expected {first}{extra}")

    check(names(port_device_ids, CORE_ROLE), service.switch, second.switch if second else None, "core port")
    check(
        names(gateway_device_ids, EDGE_ROLE),
        service.edge_router,
        second.edge_router if second else None,
        "edge gateway interface",
    )

    if vlan_count != 1:
        problems.append(f"expected one VLAN, found {vlan_count}")
    return problems


def missing_repository_items(
    tiers: Iterable[str],
    customers: Iterable[str],
    queries: Iterable[str],
    generators: Iterable[str],
) -> list[str]:
    """List the repository items that the import has not loaded yet."""
    tier_names, customer_names = set(tiers), set(customers)
    missing = [f"tier {name}" for name in EXPECTED_TIERS if name not in tier_names]
    missing += [f"customer {name}" for name in EXPECTED_CUSTOMERS if name not in customer_names]
    if QUERY_NAME not in set(queries):
        missing.append(f"query {QUERY_NAME}")
    if GENERATOR_NAME not in set(generators):
        missing.append(f"generator {GENERATOR_NAME}")
    return missing


def repository_import_action(sync_status: str) -> str:
    """What the seed does for this repository sync status.

    "done" when the repository is in sync, "reimport" after an import error, and "wait" while an
    import runs or for any other status.
    """
    if sync_status == REPOSITORY_IN_SYNC:
        return "done"
    if sync_status == REPOSITORY_IMPORT_ERROR:
        return "reimport"
    return "wait"


def pick_open_proposed_change(rows: Iterable[ProposedChangeRow], change: MaintenanceChange) -> str | None:
    """Return the id of an open proposed change with this name from this branch, or None."""
    for row in rows:
        if row.name == change.proposed_change_name and row.state == OPEN_STATE and row.source_branch == change.branch:
            return row.id
    return None


def validators_finished(validators: Sequence[ValidatorRow], required: Iterable[str] = ()) -> bool:
    """True when there is at least one validator, every `required` label is present, and all are completed.

    Infrahub creates validators after the proposed change, so an empty list
    means the pipeline has not started, not that it finished. The user check
    validators appear later than the data integrity validator, so the seed
    names the Gold outage guard in `required`.
    """
    labels = {row.label for row in validators}
    return (
        bool(validators)
        and all(label in labels for label in required)
        and all(row.state == VALIDATOR_COMPLETED for row in validators)
    )


def failed_validators(validators: Iterable[ValidatorRow]) -> list[str]:
    """Labels of the validators whose conclusion is failure."""
    return [row.label or "(no label)" for row in validators if row.conclusion == VALIDATOR_FAILURE]


def pipeline_report(change: MaintenanceChange, validators: Sequence[ValidatorRow]) -> list[str]:
    """Lines that describe a finished pipeline; a failure of the Gold outage guard is expected on a blocking change.

    The seed never fails on a validator's conclusion: these lines only say whether each result is the expected one.
    """
    lines: list[str] = []
    guard = [row for row in validators if row.label == GUARD_VALIDATOR_LABEL]
    if not guard:
        lines.append(f"{change.proposed_change_name}: unexpected, no {GUARD_VALIDATOR_LABEL} validator")
    for row in guard:
        failed = row.conclusion == VALIDATOR_FAILURE
        if failed and change.guard_blocks:
            lines.append(f"{change.proposed_change_name}: {row.label} failed, as expected; the merge is blocked")
        elif not failed and not change.guard_blocks:
            lines.append(f"{change.proposed_change_name}: {row.label} passed, as expected")
        else:
            outcome = "failed" if failed else f"concluded {row.conclusion}"
            lines.append(f"{change.proposed_change_name}: unexpected, {row.label} {outcome}")
    lines.extend(
        f"{change.proposed_change_name}: validator {label} concluded failure"
        for label in failed_validators(row for row in validators if row.label != GUARD_VALIDATOR_LABEL)
    )
    return lines


def wait_until(check: Callable[[], bool], timeout_s: float, what: str, interval_s: float | None = None) -> None:
    """Call `check` every `interval_s` seconds (POLL_INTERVAL_S by default) until it returns True.

    Raise SeedError after `timeout_s`.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        if check():
            return
        if time.monotonic() >= deadline:
            raise SeedError(f"Timed out after {timeout_s:.0f} s waiting for {what}")
        time.sleep(POLL_INTERVAL_S if interval_s is None else interval_s)


# I/O steps


def build_client() -> InfrahubClientSync:
    """Build the seed client from INFRAHUB_ADDRESS; the SDK reads INFRAHUB_API_TOKEN itself."""
    return InfrahubClientSync(address=os.environ["INFRAHUB_ADDRESS"])


def _names(client: InfrahubClientSync, kind: type) -> list[str]:
    return [str(node.name.value) for node in client.all(kind=kind, branch=MAIN_BRANCH)]


def wait_for_repository(client: InfrahubClientSync) -> None:
    """Step 1: wait until the repository import has loaded what the seed needs."""
    missing: list[str] = []

    def loaded() -> bool:
        nonlocal missing
        try:
            missing = missing_repository_items(
                tiers=_names(client, ServiceTier),
                customers=_names(client, OrganizationCustomer),
                queries=_names(client, CoreGraphQLQuery),
                generators=_names(client, CoreGeneratorDefinition),
            )
        except (SchemaNotFoundError, GraphQLError) as exc:
            # The schema of this feature is not loaded yet.
            missing = [f"schema ({exc})"]
        return not missing

    print("Waiting for the repository import...")
    try:
        wait_until(loaded, REPOSITORY_TIMEOUT_S, "the repository import")
    except SeedError as exc:
        raise SeedError(f"Step 1: {exc}; still missing: {', '.join(missing)}") from exc
    wait_for_repository_in_sync(client)


def wait_for_repository_in_sync(client: InfrahubClientSync) -> None:
    """Step 1: wait until no repository import runs and the repository is in sync.

    Infrahub can import the same commit again right after the first import, from its periodic
    repository sync. A schema load during that import can make the import fail, and the repository
    then reads "error-import". In that case the seed imports the last commit again, up to
    REIMPORT_ATTEMPTS times.
    """
    reimports = 0

    def in_sync() -> bool:
        nonlocal reimports
        repository = client.get(kind=CoreGenericRepository, name__value=REPOSITORY_NAME, branch=MAIN_BRANCH)
        action = repository_import_action(str(repository.sync_status.value))
        if action != "reimport":
            return action == "done"
        if reimports >= REIMPORT_ATTEMPTS:
            raise SeedError(
                f"Step 1: the import of repository {REPOSITORY_NAME} failed {reimports + 1} times; "
                "the task worker log names the file and object that failed"
            )
        reimports += 1
        print(f"The repository import failed; importing the last commit again (attempt {reimports})...")
        client.execute_graphql(query=REIMPORT_MUTATION, variables={"id": repository.id}, branch_name=MAIN_BRANCH)
        wait_until(
            lambda: (
                client.get(
                    kind=CoreGenericRepository, name__value=REPOSITORY_NAME, branch=MAIN_BRANCH
                ).sync_status.value
                != REPOSITORY_IMPORT_ERROR
            ),
            REIMPORT_START_TIMEOUT_S,
            "the repository import to start again",
            ARTIFACT_POLL_INTERVAL_S,
        )
        return False

    try:
        wait_until(
            in_sync, REPOSITORY_TIMEOUT_S, f"repository {REPOSITORY_NAME} to be in sync", ARTIFACT_POLL_INTERVAL_S
        )
    except SeedError as exc:
        message = str(exc)
        raise SeedError(message if message.startswith("Step 1") else f"Step 1: {message}") from exc


def _wait_for_node(client: InfrahubClientSync, kind: type, name: str, what: str, step: int = 2) -> Any:  # noqa: ANN401 - an SDK node
    """The node of `kind` named `name` on main, once the repository import has loaded it."""
    found: list[Any] = []

    def loaded() -> bool:
        nonlocal found
        found = client.filters(kind=kind, name__value=name, branch=MAIN_BRANCH)
        return bool(found)

    try:
        wait_until(loaded, REPOSITORY_TIMEOUT_S, what, ARTIFACT_POLL_INTERVAL_S)
    except SeedError as exc:
        raise SeedError(f"Step {step}: {exc}") from exc
    return found[0]


# The description Infrahub shows for each repository item that `.infrahub.yml` has no `description` key for.
# A repository import does not change these descriptions, so the seed sets them once the import has run.
REPOSITORY_DESCRIPTIONS: dict[tuple[type, str], str] = {
    (CoreCheckDefinition, "gold_outage_guard"): (
        "Fails a proposed change that leaves an active service with fewer separate paths than its tier requires."
    ),
    (CoreGeneratorDefinition, GENERATOR_NAME): (
        "Allocates the switch port, VLAN, IP prefix and edge router gateway of each Dedicated Internet order."
    ),
    (CoreArtifactDefinition, "Affected customers"): (
        "Lists the customers each proposed change affects, with their tier, their services and whether they "
        "are notified."
    ),
    (CoreArtifactDefinition, COST_DEFINITION): (
        "Gives each active service's share of the device and circuit costs of its paths, as a CSV file."
    ),
    (CoreArtifactDefinition, "Startup Config"): "Gives the startup configuration of each device.",
    (CoreGraphQLQuery, QUERY_NAME): (
        "Reads each service's customer, tier and devices, each device's status and each tier's required separate paths."
    ),
    (CoreGraphQLQuery, "cost_of_service"): (
        "Reads the list prices and active interfaces of each service's devices and the upstream interfaces of each "
        "edge router."
    ),
    (CoreGraphQLQuery, "dedicated_internet_info"): (
        "Reads one Dedicated Internet order and the resources its generator allocates."
    ),
    (
        CoreGraphQLQuery,
        "device_info",
    ): "Reads a device's interfaces and its site's VLANs for its startup configuration.",
}


def describe_repository_items(client: InfrahubClientSync) -> None:
    """Step 1: set the description of each item in REPOSITORY_DESCRIPTIONS on main.

    Safe to run again: an item whose description already matches is not saved.
    """
    for (kind, name), description in REPOSITORY_DESCRIPTIONS.items():
        node = _wait_for_node(client, kind, name, f"{kind.__name__} {name}", step=1)
        if node.description.value == description:
            print(f"{name}: description set, not rewritten")
            continue
        node.description.value = description
        node.save()
        print(f"{name}: description set")


def load_upstream_circuits(client: InfrahubClientSync, run: Callable[[str], None]) -> None:
    """Step 1: load the circuit schema on main, wait until main has it, then its menu item and the upstream circuits.

    A repository import that ran during the schema load can fail, so the step then waits until the
    repository is in sync, and imports the last commit again if the import failed.
    The circuits set the Ethernet4 of each edge router to active, so this runs before the services.
    Safe to run again: the schema load changes nothing when the schema is loaded, and the menu and
    object loads update the menu item, circuits and interfaces that exist.
    """
    print("Loading the circuit schema...")
    try:
        run(f"infrahubctl schema load {CIRCUIT_SCHEMA} --branch {MAIN_BRANCH} --wait {SCHEMA_WAIT_S}")
        wait_until(
            lambda: CIRCUIT_KIND in client.schema.all(branch=MAIN_BRANCH, refresh=True),
            REPOSITORY_TIMEOUT_S,
            "the circuit schema",
            ARTIFACT_POLL_INTERVAL_S,
        )
    except SeedError as exc:
        raise SeedError(f"Step 1: {exc}") from exc
    wait_for_repository_in_sync(client)
    try:
        run(f"infrahubctl menu load {CIRCUIT_MENU_FILE} --branch {MAIN_BRANCH}")
        print("Loading the upstream circuits...")
        run(f"infrahubctl object load {UPSTREAM_CIRCUITS_FILE} --branch {MAIN_BRANCH}")
    except SeedError as exc:
        raise SeedError(f"Step 1: {exc}") from exc


def _devices(client: InfrahubClientSync) -> dict[str, DeviceInfo]:
    return {
        str(device.id): DeviceInfo(name=str(device.name.value), role=device.role.value)
        for device in client.all(kind=DcimDevice, branch=MAIN_BRANCH)
    }


def _device_id(devices: Mapping[str, DeviceInfo], name: str) -> str:
    for device_id, info in devices.items():
        if info.name == name:
            return device_id
    raise SeedError(f"Device {name} not found on {MAIN_BRANCH}")


def seed_services(client: InfrahubClientSync) -> None:
    """Step 2: create each missing service on main and pin its switch with one free customer port."""
    devices = _devices(client)
    for row in SEED_SERVICES:
        found = client.filters(
            kind=ServiceDedicatedInternet, service_identifier__value=row.service_identifier, branch=MAIN_BRANCH
        )
        if found:
            service = found[0]
            if service.requested_by.value != row.requested_by or service.request_reason.value != row.request_reason:
                # Only the request record is brought in line with the seed list; every other field stays as it is.
                service.requested_by.value = row.requested_by
                service.request_reason.value = row.request_reason
                service.save()
                print(f"{row.service_identifier}: exists, request record updated, nothing else rewritten")
            else:
                print(f"{row.service_identifier}: exists, not rewritten")
        else:
            service = client.create(
                kind=ServiceDedicatedInternet,
                branch=MAIN_BRANCH,
                service_identifier=row.service_identifier,
                account_reference=row.customer,
                requested_by=row.requested_by,
                request_reason=row.request_reason,
                status="draft",
                bandwidth=str(row.bandwidth_mbps),
                ip_package=row.ip_package,
                member_of_groups=[GENERATOR_GROUP],
                location=[row.site],
                customer=[row.customer],
                tier=[row.tier],
            )
            service.save(allow_upsert=True)
            print(f"{row.service_identifier}: created")

        linked = client.filters(kind=DcimInterface, service__ids=[service.id], branch=MAIN_BRANCH)
        if has_core_port((interface.device.id for interface in linked), devices):
            continue

        switch_ports = {
            str(port.id): port
            for port in client.filters(
                kind=DcimInterfaceL2, device__ids=[_device_id(devices, row.switch)], branch=MAIN_BRANCH
            )
        }
        chosen = choose_free_port(
            PortRow(
                id=port_id,
                name=str(port.name.value),
                role=port.role.value,
                status=port.status.value,
                service_id=port.service.id,
            )
            for port_id, port in switch_ports.items()
        )
        if chosen is None:
            raise SeedError(f"Step 2: no free customer port on {row.switch} for {row.service_identifier}")

        # The link is `direction: inbound` on the service side, so it is written from the interface,
        # as the generator does in allocate_port.
        port = switch_ports[chosen.id]
        port.service = service
        port.save(allow_upsert=True)
        print(f"{row.service_identifier}: pinned to {row.switch} {chosen.name}")


def generator_command(service_identifier: str, branch: str = MAIN_BRANCH) -> str:
    return f"infrahubctl generator {GENERATOR_NAME} service_identifier={service_identifier} --branch {branch}"


def run_generators(client: InfrahubClientSync, run: Callable[[str], None]) -> None:
    """Step 2: run the generator for each service on main, then check its port, gateway and VLAN.

    `run` executes a shell command and raises when it exits non-zero.
    """
    devices: dict[str, DeviceInfo] | None = None
    for row in SEED_SERVICES:
        print(f"{row.service_identifier}: running {GENERATOR_NAME}")
        try:
            run(generator_command(row.service_identifier))
        except SeedError as exc:
            raise SeedError(f"Step 2: generator failed for {row.service_identifier}: {exc}") from exc

        if devices is None:
            devices = _devices(client)
        service = client.get(
            kind=ServiceDedicatedInternet, service_identifier__value=row.service_identifier, branch=MAIN_BRANCH
        )
        # Read each allocation from the side that stores the link (all are `direction: inbound` on the service).
        ports = client.filters(kind=DcimInterfaceL2, service__ids=[service.id], branch=MAIN_BRANCH)
        gateways = client.filters(kind=DcimInterfaceL3, service__ids=[service.id], branch=MAIN_BRANCH)
        vlans = client.filters(kind=IpamVLAN, service__ids=[service.id], branch=MAIN_BRANCH)
        problems = allocation_problems(
            row,
            port_device_ids=[port.device.id for port in ports],
            gateway_device_ids=[gateway.device.id for gateway in gateways],
            vlan_count=len(vlans),
            devices=devices,
        )
        if problems:
            raise SeedError(f"Step 2: allocation check failed for {row.service_identifier}: {'; '.join(problems)}")


def _free_port(client: InfrahubClientSync, switch_id: str) -> Any:  # noqa: ANN401 - an SDK node
    """The lowest free customer port on the switch, or None."""
    switch_ports = {
        str(port.id): port for port in client.filters(kind=DcimInterfaceL2, device__ids=[switch_id], branch=MAIN_BRANCH)
    }
    chosen = choose_free_port(
        PortRow(
            id=port_id,
            name=str(port.name.value),
            role=port.role.value,
            status=port.status.value,
            service_id=port.service.id,
        )
        for port_id, port in switch_ports.items()
    )
    return switch_ports[chosen.id] if chosen is not None else None


def add_second_paths(client: InfrahubClientSync) -> None:
    """Step 2: add a second path to each service in SECOND_PATHS, after the generator gave it the first one.

    A second path is one free customer port on the other switch, set up like the generator sets up the
    first port, and one gateway interface `vlan_<vlan id>` on the other edge router, with no IP address.
    Safe to run again: a service that already has a port on that switch is left as it is. The port is
    saved after the gateway interface, so a run that stopped between the two saves completes both.
    """
    devices = _devices(client)
    for path in SECOND_PATHS:
        service = client.get(
            kind=ServiceDedicatedInternet, service_identifier__value=path.service_identifier, branch=MAIN_BRANCH
        )
        switch_id = _device_id(devices, path.switch)
        ports = client.filters(kind=DcimInterfaceL2, service__ids=[service.id], branch=MAIN_BRANCH)
        if any(port.device.id == switch_id for port in ports):
            print(f"{path.service_identifier}: second path on {path.switch} exists, not rewritten")
            continue

        vlans = client.filters(kind=IpamVLAN, service__ids=[service.id], branch=MAIN_BRANCH)
        if len(vlans) != 1:
            raise SeedError(f"Step 2: expected one VLAN for {path.service_identifier}, found {len(vlans)}")
        vlan = vlans[0]
        vlan_number = vlan.vlan_id.value

        port = _free_port(client, switch_id)
        if port is None:
            raise SeedError(f"Step 2: no free customer port on {path.switch} for {path.service_identifier}")
        port.enabled.value = True
        port.status.value = "active"
        port.l2_mode.value = "Access"
        port.role.value = CUSTOMER_PORT_ROLE
        port.description.value = f"Second path for service {path.service_identifier}"
        port.speed.value = int(service.bandwidth.value)
        port.service = service
        port.untagged_vlan = vlan

        # The gateway is saved before the port. The port on the other switch is what marks the second path
        # as done on a later run, so a run that stops between the two saves adds the port next time, and
        # the gateway save is an upsert.
        gateway = client.create(
            kind=DcimInterfaceL3,
            branch=MAIN_BRANCH,
            name=f"vlan_{vlan_number}",
            speed=1000,
            device={"id": _device_id(devices, path.edge_router)},
            status="active",
            role=CUSTOMER_PORT_ROLE,
            description=f"Second path gateway interface for service {path.service_identifier}",
            enabled=True,
            service=service,
        )
        gateway.save(allow_upsert=True)
        # The port settings follow `allocate_port` in generators/implement_dedicated_internet.py. The seed
        # client does not track what it saves, so the port joins no group, as the generator saves it.
        port.save(allow_upsert=True)
        print(
            f"{path.service_identifier}: second path added, {path.switch} {port.name.value} "
            f"and {path.edge_router} vlan_{vlan_number}"
        )


def ensure_outreach_webhook(client: InfrahubClientSync) -> None:
    """Step 2: create the inactive outreach webhook on main when it is missing.

    An existing webhook is left as it is, so a team that set its CRM URL and activated it keeps both.
    The webhook's transform comes from the repository import, so the step waits until it is loaded.
    """
    name = OUTREACH_WEBHOOK["name"]
    if client.filters(kind=CoreCustomWebhook, name__value=name, branch=MAIN_BRANCH):
        print(f"{name}: webhook exists, not rewritten")
        return

    transform = _wait_for_node(client, CoreTransformPython, OUTREACH_TRANSFORM, f"the transform {OUTREACH_TRANSFORM}")
    webhook = client.create(kind=CoreCustomWebhook, branch=MAIN_BRANCH, transformation=transform, **OUTREACH_WEBHOOK)
    webhook.save()
    print(f"{name}: webhook created, inactive, with the placeholder CRM URL {OUTREACH_WEBHOOK['url']}")


def _cost_csv(client: InfrahubClientSync) -> str | None:
    return read_artifact(COST_ARTIFACT, branch=MAIN_BRANCH, client=client)


def request_cost_of_service(client: InfrahubClientSync) -> CostRequest:
    """Step 2: ask Infrahub to regenerate the "Cost of service" artifact on main, which now has the services.

    Infrahub generated the artifact when the repository import loaded its definition, before the services
    existed. `generate` posts to `/api/artifact/generate/<definition id>`, which only queues the work.
    """
    definition = _wait_for_node(
        client, CoreArtifactDefinition, COST_DEFINITION, f"the artifact definition {COST_DEFINITION}"
    )
    request = CostRequest(definition, _cost_csv(client), time.monotonic())
    definition.generate()
    print(f"{COST_DEFINITION}: generating the artifact on main...")
    return request


def _has_service_rows(content: str | None) -> bool:
    """True when the CSV has rows under its header."""
    return len((content or "").splitlines()) > 1


def wait_for_cost_of_service(client: InfrahubClientSync, request: CostRequest) -> None:
    """Step 2: wait until the "Cost of service" artifact changes after the request, then holds service rows.

    With no change after ARTIFACT_RESEND_S, the request is posted once more. With no change after the second
    request either, an artifact that already has service rows counts as current: an earlier seed run
    generated the same CSV, so Infrahub keeps it as it is.
    """

    def generated() -> bool:
        content = _cost_csv(client)
        if content and content != request.before:
            return True
        if time.monotonic() - request.posted_at < ARTIFACT_RESEND_S:
            return False
        if request.resent:
            return _has_service_rows(content)
        request.definition.generate()
        request.resent = True
        request.posted_at = time.monotonic()
        return False

    try:
        wait_until(generated, ARTIFACT_TIMEOUT_S, f"the {COST_DEFINITION} artifact", ARTIFACT_POLL_INTERVAL_S)
    except SeedError as exc:
        raise SeedError(f"Step 2: {exc}") from exc
    print(f"{COST_DEFINITION}: artifact generated")


def _ensure_branch(client: InfrahubClientSync, change: MaintenanceChange) -> None:
    if change.branch in client.branch.all():
        print(f"{change.branch}: exists, rebasing")
        client.branch.rebase(branch_name=change.branch)
    else:
        print(f"{change.branch}: creating")
        client.branch.create(branch_name=change.branch, sync_with_git=False, description=change.description)


def _ensure_proposed_change(client: InfrahubClientSync, change: MaintenanceChange) -> str:
    rows = [
        ProposedChangeRow(
            id=str(node.id),
            name=str(node.name.value),
            state=node.state.value,
            source_branch=str(node.source_branch.value),
        )
        for node in client.filters(kind=CoreProposedChange, name__value=change.proposed_change_name, branch=MAIN_BRANCH)
    ]
    existing = pick_open_proposed_change(rows, change)
    if existing is not None:
        print(f"{change.proposed_change_name}: reusing open proposed change")
        return existing

    proposed_change = client.create(
        kind=CoreProposedChange,
        branch=MAIN_BRANCH,
        name=change.proposed_change_name,
        description=change.description,
        source_branch=change.branch,
        destination_branch=MAIN_BRANCH,
    )
    proposed_change.save()
    print(f"{change.proposed_change_name}: opened")
    return str(proposed_change.id)


def _validators(client: InfrahubClientSync, proposed_change_id: str) -> list[ValidatorRow]:
    return [
        ValidatorRow(label=node.label.value, state=node.state.value, conclusion=node.conclusion.value)
        for node in client.filters(kind=CoreValidator, proposed_change__ids=[proposed_change_id], branch=MAIN_BRANCH)
    ]


def seed_maintenance(client: InfrahubClientSync) -> None:
    """Steps 3-4: maintenance branches, device status, proposed changes and the pipeline wait."""
    opened: list[tuple[MaintenanceChange, str]] = []
    for change in MAINTENANCE_CHANGES:
        _ensure_branch(client, change)
        device = client.get(kind=DcimDevice, name__value=change.device, branch=change.branch)
        device.status.value = MAINTENANCE_STATUS
        device.save(allow_upsert=True)
        print(f"{change.branch}: {change.device} set to {MAINTENANCE_STATUS}")
        opened.append((change, _ensure_proposed_change(client, change)))

    for change, proposed_change_id in opened:
        latest: list[ValidatorRow] = []

        def finished(proposed_change_id: str = proposed_change_id) -> bool:
            nonlocal latest
            latest = _validators(client, proposed_change_id)
            return validators_finished(latest, required=(GUARD_VALIDATOR_LABEL,))

        print(f"{change.proposed_change_name}: waiting for the pipeline")
        try:
            wait_until(finished, PIPELINE_TIMEOUT_S, f"the pipeline of {change.proposed_change_name}")
        except SeedError as exc:
            detail = "no validator appeared" if not latest else f"{len(latest)} validators not all completed"
            raise SeedError(f"Step 4: {exc} ({detail}) on branch {change.branch}") from exc
        for line in pipeline_report(change, latest):
            print(line)
        print(f"{change.proposed_change_name}: pipeline finished with {len(latest)} validators")


def run_all(client: InfrahubClientSync, run: Callable[[str], None]) -> None:
    """Every seed step, in order. `run` executes a shell command and raises SeedError when it exits non-zero."""
    wait_for_repository(client)
    describe_repository_items(client)
    load_upstream_circuits(client, run)
    seed_services(client)
    run_generators(client, run)
    add_second_paths(client)
    # The artifact renders while the maintenance changes are opened; the last step waits for it.
    cost_request = request_cost_of_service(client)
    ensure_outreach_webhook(client)
    seed_maintenance(client)
    wait_for_cost_of_service(client, cost_request)
