"""The cost lines, totals and inputs behind the Cost of Service page and the "Cost of service" artifact.

Plain functions over the result of the stored query `cost_of_service` with the
footprint of each active service added (`footprint.with_footprints`), so the
page and the CSV artifact compute the same figures. A service's footprint holds
the devices and the upstream circuits that Infrahub's path traversal reaches
from the service, as the Gold outage guard check reads them.

The circuit schema is optional, so the stored query reads no circuit type. When the
circuit schema is loaded, `with_circuits` merges the result of the circuit query
(`circuits.py`) into the stored query result: each circuit with its site and
monthly cost, and each circuit endpoint ID with its circuit. Without it there are
no circuit lines and no circuit inputs, only the hardware figures.

- Only active services carry a cost, as only active services count on the
  business impact pages.
- A path is the route through a switch and the edge router with the same
  number at the same site, both in the service's footprint (`network.pair_paths`, the rule the business
  impact pages and the Gold outage guard use). The primary
  path is the one on the switch with the lower index; the other one is the
  backup.
- A device's share for one path is its device type's list price divided by the
  number of its interfaces with status active (actual utilization).
- With the circuit schema loaded, a circuit's share for one path is the monthly cost of the circuit in the
  service's footprint that the path's edge router reaches, times the service's bandwidth, divided by the bandwidth of
  every service path through that edge router. With no bandwidth through the
  router, the line has no share and the note "no service bandwidth".
- One-time amounts (EUR) and monthly amounts (EUR per month) are never added
  together.
- Each line keeps its share unrounded. The CSV and the page show each line
  rounded to the cent; every sum adds the unrounded shares and rounds once.

The imports are relative so the Infrahub task worker can import this module
from the commit worktree as `commits.<sha>.service_catalog.cost_of_service.cost`.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

from ..business_impact.footprint import FOOTPRINTS, Footprint  # noqa: TID252 - the commit worktree import
from ..network import (  # noqa: TID252 - the commit worktree import
    EDGE_ROLE,
    integer,
    mapping,
    nodes,
    number,
    pair_paths,
    peer,
    text,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ONE_TIME = "EUR one-time"
PER_MONTH = "EUR per month"
DEMO_INPUT = "demo input"
DEVICE_TYPE_FILE = "data/06_device_type.yml"
CIRCUIT_FILE = "data/business_impact/upstream_circuits.yml"
# The keys of the circuit query result in the merged data.
CIRCUIT_ENDPOINTS = "DcimCircuitEndpoint"
CIRCUITS = "DcimCircuit"

NO_LIST_PRICE = "no list price"
NO_ACTIVE_INTERFACES = "no active interfaces"
NO_CIRCUIT = "no circuit"
NO_MONTHLY_COST = "no monthly cost"
NO_SERVICE_BANDWIDTH = "no service bandwidth"

ACTIVE = "active"

SWITCH = "switch"
ROUTER = "router"
CIRCUIT = "circuit"
PathKind = Literal["primary", "backup"]
PRIMARY: Final = "primary"
BACKUP: Final = "backup"
# How a cost is spread over the services, named as the CSV's `method` column.
PER_ACTIVE_INTERFACE = "per active interface"
BY_BANDWIDTH = "by bandwidth"

CSV_HEADER = (
    "service",
    "customer",
    "tier",
    "path",
    "part",
    "item",
    "input",
    "divisor",
    "method",
    "share",
    "unit",
    "note",
)


@dataclass(frozen=True)
class Device:
    name: str
    role: str
    index: int | None
    site: str | None
    device_type: str
    list_price: float | None
    active_interfaces: int


@dataclass(frozen=True)
class Circuit:
    circuit_id: str
    monthly_cost: float | None


@dataclass(frozen=True)
class Path:
    """A switch and the edge router with the same index, the primary path or the backup path.

    `circuit` is the upstream circuit in the service's footprint that the edge router reaches, if any.
    """

    kind: PathKind
    switch: Device
    router: Device
    circuit: Circuit | None = None

    @property
    def label(self) -> str:
        return f"{self.kind} ({self.switch.name} / {self.router.name})"


@dataclass(frozen=True)
class Service:
    identifier: str
    customer: str
    tier: str
    bandwidth: int
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class CostLine:
    """One row of the "Cost of service" CSV: one part of one path of one service. `share` is unrounded."""

    service: str
    customer: str
    tier: str
    path: str
    part: str
    item: str
    input: float | None
    divisor: int
    share: float | None
    unit: str
    note: str = ""

    @property
    def method(self) -> str:
        """How the input is spread: a device evenly per active interface, a circuit by bandwidth."""
        return BY_BANDWIDTH if self.part == CIRCUIT else PER_ACTIVE_INTERFACE


@dataclass(frozen=True)
class Shares:
    """The one-time and monthly sums of some cost lines, without the lines that have a note."""

    hardware: float
    circuit: float


@dataclass(frozen=True)
class UnusedRouter:
    """An edge router that carries no service path, and its circuit. It has no share to spread, only its costs."""

    router: str
    list_price: float | None
    circuit_id: str = ""
    monthly_cost: float | None = None


@dataclass(frozen=True)
class CostTotals:
    """The costs that no service carries, apart from the hardware and circuit shares the services carry.

    `upstream` is the unrounded sum of the share of each edge router in use that its active upstream
    interfaces carry: list price / active interfaces x active upstream interfaces.
    """

    upstream: float
    unused_routers: tuple[UnusedRouter, ...]

    @property
    def upstream_total(self) -> float:
        return round(self.upstream, 2)

    @property
    def unused_total(self) -> float:
        return round(sum(router.list_price or 0.0 for router in self.unused_routers), 2)

    @property
    def not_carried_one_time(self) -> float:
        """The upstream shares and the list prices of unused edge routers, summed unrounded and rounded once."""
        return round(self.upstream + sum(router.list_price or 0.0 for router in self.unused_routers), 2)

    @property
    def not_carried_monthly(self) -> float:
        """The monthly cost of the circuits on unused edge routers."""
        return round(sum(router.monthly_cost or 0.0 for router in self.unused_routers), 2)


@dataclass(frozen=True)
class CostInput:
    """One input value of the cost figures, with its "demo input" label and the file it comes from."""

    kind: str
    name: str
    value: float | None
    unit: str
    label: str
    source: str


# Reading the query result


def _device(node: Mapping[str, object]) -> Device:
    device_type = peer(node, "device_type")
    count = mapping(node.get("interfaces")).get("count")
    return Device(
        name=text(node, "name") or "",
        role=text(node, "role") or "",
        index=integer(node, "index"),
        site=text(peer(node, "location"), "shortname"),
        device_type=text(device_type, "name") or "",
        list_price=number(device_type, "list_price"),
        active_interfaces=count if isinstance(count, int) else 0,
    )


def _active_services(data: Mapping[str, Any]) -> list[Mapping[str, object]]:
    """The service nodes of the query result with status active."""
    return [node for node in nodes(data.get("ServiceDedicatedInternet")) if text(node, "status") == ACTIVE]


def _footprint(data: Mapping[str, Any], identifier: str) -> Footprint:
    """The service's footprint. Raises `ValueError` when `data` holds no footprints."""
    footprints = data.get(FOOTPRINTS)
    if not isinstance(footprints, Mapping):
        message = "The query result holds no service footprints: add them with footprint.with_footprints"
        raise ValueError(message)
    footprint: Footprint = footprints.get(identifier) or Footprint()
    return footprint


def _paths(footprint: Footprint, data: Mapping[str, Any]) -> tuple[Path, ...]:
    """The service's paths (`network.pair_paths`) over the devices of its footprint, each with its circuit.

    The one on the switch with the lower index is primary.
    """
    devices = [_device(node) for node in nodes(data.get("DcimDevice")) if text(node, "name") in footprint.devices]
    by_id = _circuits(data)
    circuit_of: dict[str, Circuit | None] = {}
    for circuit_id, router in sorted(footprint.circuits.items()):
        circuit_of.setdefault(router, by_id.get(circuit_id))
    return tuple(
        Path(PRIMARY if position == 0 else BACKUP, switch, router, circuit_of.get(router.name))
        for position, (switch, router) in enumerate(pair_paths(devices))
    )


def services(data: Mapping[str, Any]) -> tuple[Service, ...]:
    """The active services of the query result with their paths, by service identifier."""
    found = [
        Service(
            identifier=(identifier := text(node, "service_identifier") or ""),
            customer=text(peer(node, "customer"), "name") or "",
            tier=text(peer(node, "tier"), "name") or "",
            bandwidth=integer(node, "bandwidth") or 0,
            paths=_paths(_footprint(data, identifier), data),
        )
        for node in _active_services(data)
    ]
    return tuple(sorted(found, key=lambda service: service.identifier))


def _edge_routers(data: Mapping[str, Any]) -> list[Mapping[str, object]]:
    return [node for node in nodes(data.get("DcimDevice")) if text(node, "role") == EDGE_ROLE]


def with_circuits(data: Mapping[str, Any], circuit_data: Mapping[str, Any] | None) -> dict[str, Any]:
    """The stored query result with the circuit query result added; unchanged when there is none."""
    return {**data, **(circuit_data or {})}


def has_circuits(data: Mapping[str, Any]) -> bool:
    """True when `data` holds a circuit query result, so the circuit schema is loaded."""
    return CIRCUIT_ENDPOINTS in data


def _circuit_of(node: Mapping[str, object]) -> Circuit | None:
    """The circuit of a circuit node, or None when it has no circuit ID."""
    circuit_id = text(node, "circuit_id")
    return Circuit(circuit_id, number(node, "monthly_cost")) if circuit_id else None


def _circuits(data: Mapping[str, Any]) -> dict[str, Circuit]:
    """Each circuit of the circuit query, by circuit ID."""
    found = {}
    for node in nodes(data.get(CIRCUITS)):
        if circuit := _circuit_of(node):
            found[circuit.circuit_id] = circuit
    return found


def _endpoint_circuits(data: Mapping[str, Any]) -> dict[str, Circuit]:
    """The circuit of each circuit endpoint, by endpoint ID."""
    found = {}
    for endpoint in nodes(data.get(CIRCUIT_ENDPOINTS)):
        if (endpoint_id := endpoint.get("id")) and (circuit := _circuit_of(peer(endpoint, "circuit"))):
            found[str(endpoint_id)] = circuit
    return found


def _circuit(router: Mapping[str, object], by_endpoint: Mapping[str, Circuit]) -> Circuit | None:
    """The circuit connected to the first upstream interface of `router` that has one."""
    for interface in nodes(router.get("upstream")):
        endpoint_id = peer(interface, "connected_endpoint").get("id")
        if endpoint_id and (circuit := by_endpoint.get(str(endpoint_id))):
            return circuit
    return None


def circuits(data: Mapping[str, Any]) -> dict[str, Circuit]:
    """The upstream circuit of each edge router that has one, by router name. Empty without the circuit schema.

    Read from the router's upstream interface, for the edge routers that carry no service path: no
    service's footprint reaches their circuit.
    """
    by_endpoint = _endpoint_circuits(data)
    return {
        text(router, "name") or "": circuit
        for router in _edge_routers(data)
        if (circuit := _circuit(router, by_endpoint)) is not None
    }


def router_bandwidth(found: Iterable[Service]) -> dict[str, int]:
    """The bandwidth in Mbit/s of every service path through each edge router, by router name."""
    total: Counter[str] = Counter()
    for service in found:
        for path in service.paths:
            total[path.router.name] += service.bandwidth
    return dict(total)


# Cost lines


def _device_line(service: Service, path: Path, part: str, device: Device) -> CostLine:
    share: float | None = None
    note = ""
    if device.list_price is None:
        note = NO_LIST_PRICE
    elif device.active_interfaces == 0:
        note = NO_ACTIVE_INTERFACES
    else:
        share = device.list_price / device.active_interfaces
    return CostLine(
        service.identifier,
        service.customer,
        service.tier,
        path.label,
        part,
        device.name,
        device.list_price,
        device.active_interfaces,
        share,
        ONE_TIME,
        note,
    )


def _circuit_line(service: Service, path: Path, circuit: Circuit | None, bandwidth: int) -> CostLine:
    share: float | None = None
    note = ""
    if circuit is None:
        note = NO_CIRCUIT
    elif circuit.monthly_cost is None:
        note = NO_MONTHLY_COST
    elif bandwidth <= 0:
        note = NO_SERVICE_BANDWIDTH
    else:
        share = circuit.monthly_cost * service.bandwidth / bandwidth
    return CostLine(
        service.identifier,
        service.customer,
        service.tier,
        path.label,
        CIRCUIT,
        circuit.circuit_id if circuit else "",
        circuit.monthly_cost if circuit else None,
        bandwidth,
        share,
        PER_MONTH,
        note,
    )


def cost_lines(data: Mapping[str, Any]) -> list[CostLine]:
    """One line per service, path and part, sorted by service, then path (primary first), then part.

    Without the circuit schema, a path has no circuit line.
    """
    found = services(data)
    with_circuit = has_circuits(data)
    bandwidth = router_bandwidth(found)
    lines: list[CostLine] = []
    for service in found:
        for path in service.paths:
            lines.extend(
                (
                    _device_line(service, path, SWITCH, path.switch),
                    _device_line(service, path, ROUTER, path.router),
                )
            )
            if with_circuit:
                lines.append(_circuit_line(service, path, path.circuit, bandwidth[path.router.name]))
    return lines


def service_lines(lines: Iterable[CostLine], service: str) -> list[CostLine]:
    return [line for line in lines if line.service == service]


def shares(lines: Sequence[CostLine]) -> Shares:
    """The hardware share (one-time) and the circuit share (per month) of `lines`, each without lines that have a note.

    Each sum adds the unrounded shares and rounds once, to the cent.
    """
    counted = [line for line in lines if not line.note and line.share is not None]
    return Shares(
        hardware=round(sum(line.share or 0.0 for line in counted if line.unit == ONE_TIME), 2),
        circuit=round(sum(line.share or 0.0 for line in counted if line.unit == PER_MONTH), 2),
    )


def _upstream(router: Mapping[str, object]) -> float:
    """The share of the router's list price that its active upstream interfaces carry; 0 when there is none."""
    device = _device(router)
    upstream_active = sum(1 for interface in nodes(router.get("upstream")) if text(interface, "status") == ACTIVE)
    if device.list_price is None or device.active_interfaces == 0:
        return 0.0
    return device.list_price / device.active_interfaces * upstream_active


def totals(data: Mapping[str, Any]) -> CostTotals:
    """The costs that no service carries.

    - The share carried by the upstream interfaces of the edge routers that carry at least one service path.
    - The list price of each edge router that carries no service path, and its circuit.
    """
    carrying = set(router_bandwidth(services(data)))
    by_router = circuits(data)
    routers = sorted(
        ((_device(router), router) for router in _edge_routers(data) if text(router, "name")),
        key=lambda pair: pair[0].name,
    )
    upstream = sum(_upstream(node) for device, node in routers if device.name in carrying)
    unused = []
    for device, _ in routers:
        if device.name in carrying:
            continue
        circuit = by_router.get(device.name)
        unused.append(
            UnusedRouter(
                device.name,
                device.list_price,
                circuit.circuit_id if circuit else "",
                circuit.monthly_cost if circuit else None,
            )
        )
    return CostTotals(upstream, tuple(unused))


# Inputs and CSV


def inputs(data: Mapping[str, Any]) -> list[CostInput]:
    """Each device type's list price and each circuit's monthly cost, labelled "demo input", with its file."""
    devices = [_device(node) for node in nodes(data.get("DcimDevice"))]
    device_types = {device.device_type: device.list_price for device in devices if device.device_type}
    found = [
        CostInput("Device type", name, price, ONE_TIME, DEMO_INPUT, DEVICE_TYPE_FILE)
        for name, price in sorted(device_types.items())
    ]
    found += [
        CostInput("Circuit", circuit.circuit_id, circuit.monthly_cost, PER_MONTH, DEMO_INPUT, CIRCUIT_FILE)
        for circuit in sorted(_circuits(data).values(), key=lambda circuit: circuit.circuit_id)
    ]
    return found


def number_text(value: float | None, *, grouped: bool = False, cents: bool = False) -> str:
    """A number rounded to the cent, as text; empty for no value.

    With `cents` it always has two decimals; without, a whole number has none. `grouped` adds thousands
    separators: "6000", "1908.40", "6,000", "1,200.00".
    """
    if value is None:
        return ""
    rounded = round(value, 2)
    decimals = 2 if cents or not float(rounded).is_integer() else 0
    return f"{rounded:{',' if grouped else ''}.{decimals}f}"


def to_csv(lines: Iterable[CostLine]) -> str:
    """The "Cost of service" CSV: a header row and one row per line, in the given order."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for line in lines:
        writer.writerow(
            (
                line.service,
                line.customer,
                line.tier,
                line.path,
                line.part,
                line.item,
                number_text(line.input),
                line.divisor,
                line.method,
                number_text(line.share, cents=True),
                line.unit,
                line.note,
            )
        )
    return buffer.getvalue()
