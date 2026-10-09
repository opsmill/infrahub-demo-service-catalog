"""Seed task for the business impact demo.

`invoke seed` calls the four step functions in order. The step numbers in the
error messages match the steps the installation guide lists:

1. `wait_for_repository`: wait until the repository import has loaded the
   tiers, customers, stored query and generator definition.
2. `seed_services`: create each of the twelve services on main when it is
   missing, and pin its switch by linking one free customer port.
   `run_generators`: run the provisioning generator for each service on main,
   then check that the service has its port, gateway and VLAN.
3-4. `seed_maintenance`: create or rebase the four maintenance branches, move
   services on the branch where the change says so, set the device to
   maintenance on each, open the proposed changes and wait for
   their pipelines. The Gold outage guard is expected to fail on the Paris and
   Brussels changes and to pass on New York and on the Paris change with the
   Gold services moved first; the wait reports each as an expected result.

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
    CoreGeneratorDefinition,
    CoreGeneratorGroup,
    CoreGraphQLQuery,
    CoreProposedChange,
    CoreValidator,
)
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

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

MAIN_BRANCH = "main"
GENERATOR_NAME = "dedicated_internet_generator"
GENERATOR_GROUP = "automated_dedicated_internet"
STORED_QUERY_NAME = "business_impact_services"
CORE_ROLE = "core"
EDGE_ROLE = "edge"
CUSTOMER_PORT_ROLE = "customer"
FREE_PORT_STATUS = "free"
MAINTENANCE_STATUS = "maintenance"
OPEN_STATE = "open"
VALIDATOR_COMPLETED = "completed"
VALIDATOR_FAILURE = "failure"
# Infrahub labels a check definition's validator "Check: <definition name>" (git/tasks.py in 1.11.4).
GUARD_VALIDATOR_LABEL = "Check: gold_outage_guard"

POLL_INTERVAL_S = 5.0
REPOSITORY_TIMEOUT_S = 600.0
PIPELINE_TIMEOUT_S = 600.0

# Base monthly price per bandwidth, before the tier multiplier.
BASE_PRICE_EUR: dict[int, int] = {100: 400, 1000: 1200, 10000: 4500}
# Mirrors `price_multiplier_pct` in data/10_customers_tiers.yml; the unit test checks they agree.
TIER_MULTIPLIER_PCT: dict[str, int] = {"Gold": 180, "Silver": 130, "Bronze": 100}
EXPECTED_TIERS: tuple[str, ...] = ("Gold", "Silver", "Bronze")
EXPECTED_CUSTOMERS: tuple[str, ...] = ("Northbank", "Helix Health", "Maison Verte", "Rapid Freight")


class SeedError(RuntimeError):
    """A seed step failed; the message names the step and the service or branch."""


def monthly_charge(bandwidth_mbps: int, tier_multiplier_pct: int) -> int:
    """Return the monthly charge in EUR: base price for the bandwidth times the tier multiplier."""
    if bandwidth_mbps not in BASE_PRICE_EUR:
        raise ValueError(f"No base price for bandwidth {bandwidth_mbps} Mbps")
    charge, remainder = divmod(BASE_PRICE_EUR[bandwidth_mbps] * tier_multiplier_pct, 100)
    if remainder:
        raise ValueError(f"Charge for {bandwidth_mbps} Mbps at {tier_multiplier_pct}% is not a whole euro")
    return charge


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

    @property
    def monthly_charge(self) -> int:
        return monthly_charge(self.bandwidth_mbps, TIER_MULTIPLIER_PCT[self.tier])


@dataclass(frozen=True)
class MaintenanceChange:
    """A maintenance branch, the device it sets to maintenance and its proposed change."""

    branch: str
    device: str
    proposed_change_name: str
    description: str
    # True when the change takes a Gold service out of service, so the Gold outage guard must fail it.
    guard_blocks: bool
    # Services moved to another switch on the branch before the device goes into maintenance, as
    # (service identifier, switch). The generator then puts each one on the edge router with that switch's index.
    moves: tuple[tuple[str, str], ...] = ()


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
        request_reason="Internet access for the Brussels branch",
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
        guard_blocks=True,
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
    MaintenanceChange(
        branch="maint-rb01-par01-moved",
        device="rb01-par01",
        proposed_change_name="Paris router 1 maintenance, Gold services moved first",
        description=(
            "Maintenance on Paris edge router 1 (rb01-par01), after moving DI-1001 and DI-1002 "
            "to Paris switch 2 and Paris edge router 2"
        ),
        guard_blocks=False,
        moves=(("DI-1001", "sw02-par01"), ("DI-1002", "sw02-par01")),
    ),
)


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
    """List what the generator did not allocate: one core port on the pinned switch, one edge gateway, one VLAN."""
    problems: list[str] = []

    def names(device_ids: Sequence[str | None], role: str) -> list[str]:
        found = (devices.get(device_id) for device_id in device_ids if device_id is not None)
        return [device.name for device in found if device is not None and device.role == role]

    core_ports = names(port_device_ids, CORE_ROLE)
    if len(core_ports) != 1:
        problems.append(f"expected one core port, found {len(core_ports)}")
    elif core_ports[0] != service.switch:
        problems.append(f"core port is on {core_ports[0]}, expected {service.switch}")

    gateways = names(gateway_device_ids, EDGE_ROLE)
    if len(gateways) != 1:
        problems.append(f"expected one edge gateway interface, found {len(gateways)}")
    elif gateways[0] != service.edge_router:
        problems.append(f"gateway is on {gateways[0]}, expected {service.edge_router}")

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
    if STORED_QUERY_NAME not in set(queries):
        missing.append(f"query {STORED_QUERY_NAME}")
    if GENERATOR_NAME not in set(generators):
        missing.append(f"generator {GENERATOR_NAME}")
    return missing


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


def wait_until(check: Callable[[], bool], timeout_s: float, what: str) -> None:
    """Call `check` every POLL_INTERVAL_S seconds until it returns True; raise SeedError after `timeout_s`."""
    deadline = time.monotonic() + timeout_s
    while True:
        if check():
            return
        if time.monotonic() >= deadline:
            raise SeedError(f"Timed out after {timeout_s:.0f} s waiting for {what}")
        time.sleep(POLL_INTERVAL_S)


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


def _devices(client: InfrahubClientSync, branch: str = MAIN_BRANCH) -> dict[str, DeviceInfo]:
    return {
        str(device.id): DeviceInfo(name=str(device.name.value), role=device.role.value)
        for device in client.all(kind=DcimDevice, branch=branch)
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
                monthly_charge=row.monthly_charge,
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


def _ensure_branch(client: InfrahubClientSync, change: MaintenanceChange) -> None:
    if change.branch in client.branch.all():
        print(f"{change.branch}: exists, rebasing")
        client.branch.rebase(branch_name=change.branch)
    else:
        print(f"{change.branch}: creating")
        client.branch.create(branch_name=change.branch, sync_with_git=False, description=change.description)


def _release_port(client: InfrahubClientSync, port: Any, branch: str) -> None:  # noqa: ANN401 - an SDK node
    """Free a customer port on `branch`, and take it out of the generator's tracking group first.

    The generator deletes the nodes of its group that a run no longer saves. It now saves the port outside
    its group, but a port saved by an earlier version of the generator is still a member, and the next run
    would delete the physical switch port instead of leaving it free.
    """
    for group in client.filters(kind=CoreGeneratorGroup, members__ids=[port.id], branch=branch):
        group.members.fetch()
        group.members.remove(port.id)
        group.save()
    port.service = None
    port.untagged_vlan = None
    port.status.value = "free"
    port.enabled.value = False
    port.description.value = None
    port.l2_mode.value = None
    port.save()


def move_services(client: InfrahubClientSync, change: MaintenanceChange, run: Callable[[str], None]) -> None:
    """Step 3: on the change's branch, move each service to its new switch and run the generator there.

    Safe to run again: a service whose port is already on the new switch is left as it is.
    """
    devices = _devices(client, change.branch)
    for service_identifier, switch in change.moves:
        service = client.get(
            kind=ServiceDedicatedInternet, service_identifier__value=service_identifier, branch=change.branch
        )
        ports = client.filters(kind=DcimInterfaceL2, service__ids=[service.id], branch=change.branch)
        target_id = _device_id(devices, switch)
        if any(port.device.id == target_id for port in ports):
            print(f"{change.branch}: {service_identifier} already on {switch}")
            continue
        for port in ports:
            if port.device.id in devices and devices[port.device.id].role == "core":
                _release_port(client, port, change.branch)

        switch_ports = {
            str(port.id): port
            for port in client.filters(kind=DcimInterfaceL2, device__ids=[target_id], branch=change.branch)
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
            raise SeedError(f"Step 3: no free customer port on {switch} for {service_identifier}")
        port = switch_ports[chosen.id]
        port.service = service
        port.save(allow_upsert=True)
        print(f"{change.branch}: {service_identifier} moved to {switch} {chosen.name}")
        try:
            run(generator_command(service_identifier, change.branch))
        except SeedError as exc:
            raise SeedError(f"Step 3: generator failed for {service_identifier} on {change.branch}: {exc}") from exc


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


def seed_maintenance(client: InfrahubClientSync, run: Callable[[str], None]) -> None:
    """Steps 3-4: maintenance branches, device status, proposed changes and the pipeline wait."""
    opened: list[tuple[MaintenanceChange, str]] = []
    for change in MAINTENANCE_CHANGES:
        _ensure_branch(client, change)
        move_services(client, change, run)
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
