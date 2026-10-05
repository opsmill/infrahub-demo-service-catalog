"""The Gold outage guard rule.

`checks/gold_outage_guard.py` runs the stored query `business_impact_services`
on the proposed change's branch and on main. For each active Gold service and
each device that is not active on the branch (`traversal_pairs`), it asks
Infrahub's path traversal whether a network path joins the two, then calls
`evaluate` with the devices each service reaches. The rule reuses the parsing
and the "out of service = device not active" rule of `blast_radius.py`.

The traversal only passes through `NETWORK_KINDS` and at most `MAX_HOPS`
relationships: service, interface, device. That is the same dependency the
Blast radius view reads from the query, so the view and the check agree. A
model where a service depends on devices further away (an access switch and
its uplinks, or a second path) raises `MAX_HOPS` and adds the link kinds,
without a new query.

A change fails when an active Gold service on the branch sits behind a device
that this change takes out of service: not active on the branch, and active
on main (or absent from main). A Gold service whose only out-of-service
devices were already out of service on main gives a warning, not an error,
so an existing problem does not block unrelated work. Nothing here imports
Streamlit or calls Infrahub.

The imports are relative on purpose: the Infrahub task worker imports this
module from the commit worktree as `commits.<sha>.service_catalog...`, where an
absolute `service_catalog` import does not resolve (see the check file).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import TYPE_CHECKING

from .blast_radius import (
    DeviceRow,
    ServiceRow,
    active_services,
    format_eur,
    join_names,
    parse_devices,
    parse_services,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

CREDIT_LABEL = "demo business input"
# Kinds a dependency path may pass through: the service, its interfaces and the devices they sit on.
NETWORK_KINDS = ("ServiceDedicatedInternet", "DcimInterfaceL2", "DcimInterfaceL3", "DcimDevice")
# Relationships from a service to a device it depends on: service > interface > device.
MAX_HOPS = 2


@dataclass(frozen=True)
class TraversalPair:
    """An active Gold service and a device that is not active on the branch: the path to look for."""

    service: str
    service_id: str
    device: str
    device_id: str


def _edges(data: Mapping[str, object], kind: str) -> list[Mapping[str, object]]:
    block = data.get(kind)
    edges = block.get("edges") if isinstance(block, dict) else None
    return [edge["node"] for edge in edges or [] if isinstance(edge, dict) and isinstance(edge.get("node"), dict)]


def _value(node: Mapping[str, object], field_name: str) -> object:
    attribute = node.get(field_name)
    return attribute.get("value") if isinstance(attribute, dict) else None


def traversal_pairs(branch_data: Mapping[str, object]) -> list[TraversalPair]:
    """Each active Gold service paired with each core or edge device that is not active on the branch."""
    gold = {service.identifier for service in active_services(parse_services(branch_data)) if service.gold}
    services = [
        (str(_value(node, "service_identifier")), str(node.get("id")))
        for node in _edges(branch_data, "ServiceDedicatedInternet")
        if _value(node, "service_identifier") in gold and node.get("id")
    ]
    out = {device.name for device in parse_devices(branch_data) if device.out_of_service}
    devices = [
        (str(_value(node, "name")), str(node.get("id")))
        for node in _edges(branch_data, "DcimDevice")
        if _value(node, "name") in out and node.get("id")
    ]
    return [
        TraversalPair(service, service_id, device, device_id)
        for service, service_id in services
        for device, device_id in devices
    ]


@dataclass
class GuardResult:
    """What the check logs: each error fails it, each warning is informational."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


def move_to_device(device: DeviceRow, devices: Iterable[DeviceRow]) -> DeviceRow | None:
    """The device with the same role at the same site and the other index, or None.

    Each seeded site has two devices per role (index 1 and 2), so the other
    index is the other device of that role at that site; the first by name
    wins if a site ever has more.
    """
    if not device.site:
        return None
    peers = [
        other
        for other in devices
        if other.name != device.name and other.role == device.role and other.site == device.site
    ]
    return min(peers, key=lambda other: other.name, default=None)


def _already_out(device: DeviceRow, main_devices: Mapping[str, DeviceRow]) -> bool:
    on_main = main_devices.get(device.name)
    return on_main is not None and on_main.out_of_service


def _caused_by_change(service: ServiceRow, main_devices: Mapping[str, DeviceRow]) -> tuple[DeviceRow, ...]:
    return tuple(device for device in service.out_of_service_devices if not _already_out(device, main_devices))


def _error_message(
    change_name: str,
    blocked: list[ServiceRow],
    devices_out: Iterable[DeviceRow],
    branch_devices: tuple[DeviceRow, ...],
) -> str:
    one = len(blocked) == 1
    noun = "service" if one else "services"
    names = join_names({service.customer for service in blocked if service.customer})
    customers = f" for {names}" if names else ""
    identifiers = ", ".join(service.identifier for service in blocked)
    credit = sum((service.monthly_sla_credit for service in blocked), Decimal(0))

    # Devices behind a service carry no site in the query; the `DcimDevice` block does.
    by_name = {device.name: device for device in branch_devices}
    unique: list[DeviceRow] = []
    for device in devices_out:
        if all(seen.name != device.name for seen in unique):
            unique.append(by_name.get(device.name) or device)
    targets = [move_to_device(device, branch_devices) for device in unique]
    pronoun = "this service" if one else "these services"
    if all(target is not None for target in targets):
        action = f"Move {pronoun} to {join_names({target.label for target in targets if target is not None})} first."
    else:
        action = f"Move {pronoun} off {join_names({device.label for device in unique})} first."

    return (
        f"{change_name} leaves {len(blocked)} Gold {noun}{customers} with no other path ({identifiers}). "
        f"Gold SLA credit exposure: {format_eur(credit)} per month ({CREDIT_LABEL}). "
        f"{action}"
    )


def _warning_message(service: ServiceRow) -> str:
    devices = join_names({device.label for device in service.out_of_service_devices})
    return (
        f"WARNING: Gold service {service.identifier} for {service.customer_label} is already out of service "
        f"on the current network, behind {devices}. This change does not cause it, so it does not block the merge."
    )


def evaluate(
    branch_data: Mapping[str, object],
    main_data: Mapping[str, object],
    change_name: str,
    reached: Mapping[str, Collection[str]] | None = None,
) -> GuardResult:
    """Apply the guard to the query result on the proposed change's branch and on main.

    `reached` maps a service identifier to the names of the devices that path traversal reached from it.
    When it is given, those devices are the ones each service depends on; when it is None, the devices
    behind the service's interfaces in the query are. There is no override: no tag, setting or threshold
    changes the result.
    """
    main_devices = {device.name: device for device in parse_devices(main_data)}
    services: list[ServiceRow] = list(active_services(parse_services(branch_data)))
    if reached is not None:
        branch_devices = {device.name: device for device in parse_devices(branch_data)}
        services = [
            replace(
                service,
                devices=tuple(
                    branch_devices[name]
                    for name in sorted(reached.get(service.identifier, ()))
                    if name in branch_devices
                ),
            )
            for service in services
        ]
    gold = [service for service in services if service.gold and service.affected]

    blocked: list[ServiceRow] = []
    devices_out: list[DeviceRow] = []
    result = GuardResult()
    for service in gold:
        caused = _caused_by_change(service, main_devices)
        if caused:
            blocked.append(service)
            devices_out.extend(caused)
        else:
            result.warnings.append(_warning_message(service))

    if blocked:
        result.errors.append(_error_message(change_name, blocked, devices_out, parse_devices(branch_data)))
    return result
