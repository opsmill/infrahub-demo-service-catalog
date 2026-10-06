"""Figures for the Single points of failure view.

The view answers "If this device failed now, unplanned, what would have no path?"
on the current network. It reads the same stored query as the Blast radius view,
`business_impact_services`, on main only, and writes nothing.

A device is a single point of failure for a service when every path of the service
passes through it. In this model each service has one path, its switch and its edge
router, so every device behind a service is a single point of failure for it.

`with_device_failed` copies the query data with one device set to not active, and
`build_blast_radius` turns that copy into the same tiles, chart and tables as the
Blast radius view. Nothing here imports Streamlit or writes to Infrahub.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from .blast_radius import (
    CORE_ROLE,
    EDGE_ROLE,
    BlastRadius,
    ServiceRow,
    active_services,
    build_blast_radius,
    join_names,
    parse_devices,
    parse_services,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# The status given to the selected device in the copy. Any status other than active is out of service.
FAILED = "failed"
ROLE_LABELS = {CORE_ROLE: "Switch", EDGE_ROLE: "Edge router"}


@dataclass(frozen=True)
class DependencyRow:
    """One device and the active Gold services that would have no path if it failed."""

    name: str
    label: str
    role: str
    gold_services: tuple[str, ...]
    customers: tuple[str, ...]
    gold_annual: int
    gold_monthly_credit: Decimal


@dataclass(frozen=True)
class SinglePoints:
    """The summary of the view: how many active Gold services have a single point of failure."""

    gold_total: int
    gold_single_point: int
    devices: tuple[DependencyRow, ...]

    @property
    def headline(self) -> str:
        if not self.gold_total:
            return "No active Gold service was found"
        noun = "service has" if self.gold_total == 1 else "services have"
        return f"{self.gold_single_point} of {self.gold_total} Gold {noun} a single point of failure"


def _single_point(service: ServiceRow) -> bool:
    """One path per service: every device behind the service is on that path."""
    return bool(service.devices)


def single_points(data: Mapping[str, object]) -> SinglePoints:
    """Active Gold services with a single point of failure, and the devices they depend on, by Gold value."""
    gold = [service for service in active_services(parse_services(data)) if service.gold]
    rows: list[DependencyRow] = []
    for device in parse_devices(data):
        depending = [service for service in gold if any(peer.name == device.name for peer in service.devices)]
        if not depending:
            continue
        rows.append(
            DependencyRow(
                name=device.name,
                label=device.label,
                role=ROLE_LABELS.get(device.role or "", device.role or ""),
                gold_services=tuple(service.identifier for service in depending),
                customers=tuple(sorted({service.customer_label for service in depending})),
                gold_annual=sum(service.annual_contract_value for service in depending),
                gold_monthly_credit=sum((service.monthly_sla_credit for service in depending), Decimal(0)),
            )
        )
    rows.sort(key=lambda row: (-row.gold_annual, row.label))
    return SinglePoints(
        gold_total=len(gold),
        gold_single_point=sum(1 for service in gold if _single_point(service)),
        devices=tuple(rows),
    )


def with_device_failed(data: Mapping[str, object], device_name: str) -> dict[str, object]:
    """A copy of the query data with `device_name` set to not active, behind every service and in the device list."""
    failed = copy.deepcopy(dict(data))

    def mark(node: object) -> None:
        if isinstance(node, dict):
            name = node.get("name")
            if isinstance(name, dict) and name.get("value") == device_name and "status" in node:
                node["status"] = {"value": FAILED}
            for value in node.values():
                mark(value)
        elif isinstance(node, list):
            for value in node:
                mark(value)

    mark(failed.get("ServiceDedicatedInternet"))
    mark(failed.get("DcimDevice"))
    return failed


def failure_headline(device_label: str, result: BlastRadius) -> str:
    """Headline for "If this device failed now": the Gold services and customers that would have no path."""
    services = list(result.affected_rows)
    gold = [row for row in services if row.tier == "Gold"]
    prefix = f"If {device_label} failed now,"
    if not services:
        return f"{prefix} every service would keep its path"
    if gold:
        noun = "service" if len(gold) == 1 else "services"
        names = join_names({row.customer for row in gold})
        return f"{prefix} {len(gold)} Gold {noun} for {names} would have no path"
    noun = "service" if len(services) == 1 else "services"
    return f"{prefix} {len(services)} {noun} would have no path, and none of them is Gold"


def failure_impact(data: Mapping[str, object], device_name: str) -> BlastRadius:
    """The Blast radius figures for the current network with `device_name` failed."""
    return build_blast_radius(with_device_failed(data, device_name), data)


def device_options(points: SinglePoints, devices: Iterable[str] = ()) -> tuple[str, ...]:
    """Device names for the picker: the devices Gold services depend on, by Gold value, then any others given."""
    names = [row.name for row in points.devices]
    return (*names, *sorted(set(devices) - set(names)))
