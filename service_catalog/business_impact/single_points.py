"""Figures for the Single points of failure view.

The view answers "If this device failed now, unplanned, what would have no path?"
on the current network. It reads the same stored query as the Planned maintenance page,
`business_impact_services`, on main only, with the footprint of each active service
(`footprint.with_footprints`), and writes nothing.

A device is a single point of failure for a service when every path of the service
passes through it. A path is the route through a switch and the edge router with the
same number at the same site (`blast_radius.paths`). A service with one path depends on both of its devices; a
service with two paths has no single point of failure among them.

`with_device_failed` copies the query data with one device set to not active, and
`build_blast_radius` turns that copy into the same tiles and table as the Blast
radius view. Nothing here imports Streamlit or writes to Infrahub.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..network import attr, nodes  # noqa: TID252 - the commit worktree import
from .blast_radius import (
    CORE_ROLE,
    EDGE_ROLE,
    GOLD,
    STATUS_DOWN,
    BlastRadius,
    ServiceRow,
    active_services,
    build_blast_radius,
    join_names,
    parse_devices,
    parse_services,
    paths,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# The status given to the selected device in the copy. Any status other than active is out of service.
FAILED = "failed"
ROLE_LABELS = {CORE_ROLE: "Switch", EDGE_ROLE: "Edge router"}


@dataclass(frozen=True)
class DependencyRow:
    """One device and the active Gold services whose every path passes through it."""

    name: str
    label: str
    role: str
    gold_services: tuple[str, ...]
    customers: tuple[str, ...]


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


def _single_point(service: ServiceRow) -> frozenset[str]:
    """The names of the devices on every path of the service.

    A service with no complete path depends on every device in its footprint.
    """
    service_paths = paths(service)
    if not service_paths:
        return frozenset(device.name for device in service.devices)
    return frozenset.intersection(*(path.names for path in service_paths))


def single_points(data: Mapping[str, object]) -> SinglePoints:
    """Active Gold services with a single point of failure, and the devices on every path of them.

    Devices are sorted by the number of Gold services that depend on them, then by name.
    """
    gold = [service for service in active_services(parse_services(data)) if service.gold]
    single = {service.identifier: _single_point(service) for service in gold}
    rows: list[DependencyRow] = []
    for device in parse_devices(data):
        depending = [service for service in gold if device.name in single[service.identifier]]
        if not depending:
            continue
        rows.append(
            DependencyRow(
                name=device.name,
                label=device.label,
                role=ROLE_LABELS.get(device.role or "", device.role or ""),
                gold_services=tuple(service.identifier for service in depending),
                customers=tuple(sorted({service.customer_label for service in depending})),
            )
        )
    rows.sort(key=lambda row: (-len(row.gold_services), row.label))
    return SinglePoints(
        gold_total=len(gold),
        gold_single_point=sum(1 for service in gold if single[service.identifier]),
        devices=tuple(rows),
    )


def with_device_failed(data: Mapping[str, object], device_name: str) -> dict[str, object]:
    """A copy of the query data with `device_name` set to not active in the device list.

    Each service reads its devices from that list, so the device is not active on every service it carries.
    """
    failed = copy.deepcopy(dict(data))
    for node in nodes(failed.get("DcimDevice")):
        if isinstance(node, dict) and attr(node, "name") == device_name and "status" in node:
            node["status"] = {"value": FAILED}
    return failed


def failure_headline(device_label: str, result: BlastRadius) -> str:
    """Headline for "If this device failed now": Gold services with no path first, then with fewer paths."""
    services = list(result.affected_rows)
    gold = [row for row in services if row.tier == GOLD]
    gold_down = [row for row in gold if row.status == STATUS_DOWN]
    prefix = f"If {device_label} failed now,"
    if not services:
        return f"{prefix} every service would keep its path"
    if gold:
        shown = gold_down or gold
        noun = "service" if len(shown) == 1 else "services"
        names = join_names({row.customer for row in shown})
        outcome = "would have no path" if gold_down else "would have fewer separate paths"
        return f"{prefix} {len(shown)} Gold {noun} for {names} {outcome}"
    noun = "service" if len(services) == 1 else "services"
    return f"{prefix} {len(services)} {noun} would be affected, and none of them is Gold"


def failure_impact(data: Mapping[str, object], device_name: str) -> BlastRadius:
    """The Planned maintenance figures for the current network with `device_name` failed."""
    return build_blast_radius(with_device_failed(data, device_name), data)
