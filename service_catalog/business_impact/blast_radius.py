"""Figures for the Planned maintenance page.

Plain functions over the `data` dict that the stored query
`business_impact_services` returns, with the footprint of each service added
(`footprint.with_footprints`). The page runs the query and the path traversal on
the selected branch and again on main, then calls `build_blast_radius`. Nothing
here imports Streamlit or writes to Infrahub, so every figure on the page is
unit-tested offline.

A path is the route a service's traffic takes through the network at a site:
it enters through a switch port, goes through a switch (role `core`), and leaves
through the edge router (role `edge`) with the same number, as the order
generator pairs them. Both devices must be in the service's footprint: the
devices Infrahub's path traversal reaches from the service through its
interfaces. Each pair is one separate path. A path is up when neither device is out of service. For each
active service, the page compares the paths that are up on main with the paths
that are up during the change: fewer, but more than 0, is "at risk"; 0 is
"down".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import starmap
from typing import TYPE_CHECKING, Final, Literal

from ..network import (  # noqa: TID252 - the commit worktree import
    CORE_ROLE,
    EDGE_ROLE,
    attr,
    integer,
    nodes,
    pair_paths,
    peer,
    text,
)
from .footprint import FOOTPRINTS, Footprint

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

CURRENT_NETWORK = "Current network"
MAIN_BRANCH = "main"
DEFAULT_CHANGE = "Paris router 1 maintenance"
SERVICE_REQUEST_TAG = "service_request"

ACTIVE = "active"
# The tier names of data/10_customers_tiers.yml. The rule of each tier (`min_paths`) comes from the data,
# but the order of the lists and the Gold-only behavior (notification, the outage guard, single points of
# failure) follow these names. A unit test fails when the names here and in the data differ.
GOLD = "Gold"
# Tiers in the order lists show them: Gold, Silver, Bronze, then any other tier by name.
TIER_ORDER: tuple[str, ...] = (GOLD, "Silver", "Bronze")
UNASSIGNED = "Unassigned"
NOT_SET = "Not set"

# A service's status during a change: fewer separate paths than on main but at least 1, or none left.
ImpactStatus = Literal["at risk", "down"]
STATUS_AT_RISK: Final = "at risk"
STATUS_DOWN: Final = "down"

NO_SERVICES_FOUND = "No services were found"
NO_SERVICE_AFFECTED = "No service is affected"

TILE_CUSTOMERS = "Customers affected"
TILE_GOLD_AT_RISK = "Gold services at risk"
TILE_DOWN = "Services down"
HELP_CUSTOMERS = "Customers with at least one active service at risk or down during this change."
HELP_GOLD_AT_RISK = (
    "Active Gold services with fewer separate paths during this change than on the current network, "
    "and at least 1 left."
)
HELP_DOWN = "Active services with no separate path during this change."
COUNTED = "Counted"


@dataclass(frozen=True)
class DeviceRow:
    """A device as the query reads it in the `DcimDevice` block."""

    name: str
    description: str | None
    role: str | None
    status: str | None
    site: str | None = None
    index: int | None = None

    @property
    def label(self) -> str:
        """Friendly name: the description, or the name when the description is empty."""
        return self.description or self.name

    @property
    def out_of_service(self) -> bool:
        """Any status other than active counts as out of service."""
        return self.status != ACTIVE


@dataclass(frozen=True)
class ServiceRow:
    """A Dedicated Internet service as the query reads it."""

    identifier: str
    status: str | None
    bandwidth_mbps: int | None
    site: str | None
    customer: str | None
    tier: str | None
    devices: tuple[DeviceRow, ...]

    @property
    def active(self) -> bool:
        return self.status == ACTIVE

    @property
    def out_of_service_devices(self) -> tuple[DeviceRow, ...]:
        """The devices the service's paths go through that are not active."""
        return tuple(device for device in self.devices if device.out_of_service)

    @property
    def affected(self) -> bool:
        """True when any device the service's paths go through is not active."""
        return bool(self.out_of_service_devices)

    @property
    def gold(self) -> bool:
        """A missing tier is never Gold."""
        return self.tier == GOLD

    @property
    def customer_label(self) -> str:
        return self.customer or UNASSIGNED

    @property
    def tier_label(self) -> str:
        return self.tier or UNASSIGNED

    def device_label(self, role: str) -> str:
        """Friendly names of the service's devices with `role`, or "Not set"."""
        labels = sorted({device.label for device in self.devices if device.role == role})
        return ", ".join(labels) if labels else NOT_SET


@dataclass(frozen=True)
class ServicePath:
    """One separate path of a service: a switch and the edge router with the same index at the same site."""

    switch: DeviceRow
    edge_router: DeviceRow

    @property
    def names(self) -> frozenset[str]:
        return frozenset({self.switch.name, self.edge_router.name})


@dataclass(frozen=True)
class ServiceImpact:
    """An active service that has fewer paths during the change than on main, or none."""

    service: ServiceRow
    paths_on_main: int
    paths_during_change: int
    status: ImpactStatus


@dataclass(frozen=True)
class Tile:
    label: str
    value: str
    help: str
    marker: str  # shown under the tile


@dataclass(frozen=True)
class AffectedServiceRow:
    """One row of the "Affected services" table, already formatted for display."""

    service: str
    customer: str
    tier: str
    bandwidth: str
    switch: str
    edge_router: str
    paths_on_main: int
    paths_during_change: int
    status: str
    # The tier's rule: the separate paths its services must keep during a change.
    rule: int


@dataclass(frozen=True)
class BlastRadius:
    """Everything the Planned maintenance page shows for one selected change."""

    no_services: bool
    headline: str
    gold_headline: bool
    tiles: tuple[Tile, ...]
    affected_rows: tuple[AffectedServiceRow, ...]


@dataclass(frozen=True)
class PickerEntry:
    label: str
    branch: str


# Parsing the query `data`


def _device(node: Mapping[str, object]) -> DeviceRow | None:
    name = text(node, "name")
    if name is None:
        return None
    return DeviceRow(
        name=name,
        description=text(node, "description"),
        role=text(node, "role"),
        status=text(node, "status"),
        site=text(peer(node, "location"), "shortname"),
        index=integer(node, "index"),
    )


def parse_services(data: Mapping[str, object]) -> tuple[ServiceRow, ...]:
    """Read every service of the query, in service identifier order, with the devices its paths go through.

    The devices come from the service's footprint (`footprint.with_footprints`), read from the `DcimDevice`
    block. A service with no footprint, such as one that is not active, has no device. Raises `ValueError`
    when `data` holds no footprints.
    """
    footprints = data.get(FOOTPRINTS)
    if not isinstance(footprints, Mapping):
        message = "The query result holds no service footprints: add them with footprint.with_footprints"
        raise ValueError(message)
    by_name = {device.name: device for device in parse_devices(data)}
    services = []
    for node in nodes(data.get("ServiceDedicatedInternet")):
        identifier = text(node, "service_identifier")
        if identifier is None:
            continue
        footprint = footprints.get(identifier) or Footprint()
        devices = tuple(by_name[name] for name in sorted(footprint.devices) if name in by_name)
        services.append(
            ServiceRow(
                identifier=identifier,
                status=text(node, "status"),
                bandwidth_mbps=integer(node, "bandwidth"),
                site=text(peer(node, "location"), "shortname"),
                customer=text(peer(node, "customer"), "name"),
                tier=text(peer(node, "tier"), "name"),
                devices=devices,
            )
        )
    return tuple(sorted(services, key=lambda service: service.identifier))


def parse_devices(data: Mapping[str, object]) -> tuple[DeviceRow, ...]:
    """Read the `DcimDevice` block of the query (on the selected branch or on main)."""
    return tuple(device for node in nodes(data.get("DcimDevice")) if (device := _device(node)) is not None)


def tier_rules(data: Mapping[str, object]) -> dict[str, int]:
    """Each tier's minimum separate paths during a change, by tier name, from the `ServiceTier` block.

    An empty or unreadable value counts as 0. A tier that is not in the block is not in the result.
    """
    rules: dict[str, int] = {}
    for node in nodes(data.get("ServiceTier")):
        name = text(node, "name")
        if name is None:
            continue
        value = attr(node, "min_paths")
        rules[name] = value if isinstance(value, int) and not isinstance(value, bool) else 0
    return rules


def tier_key(tier: str) -> tuple[int, str]:
    """Sort key for tiers: Gold, Silver, Bronze, then any other tier in name order."""
    return (TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER), tier)


def active_services(services: Iterable[ServiceRow]) -> tuple[ServiceRow, ...]:
    return tuple(service for service in services if service.active)


# Paths


def paths(service: ServiceRow) -> tuple[ServicePath, ...]:
    """The separate paths of the service: each switch with the edge router of the same index at the same site."""
    return tuple(starmap(ServicePath, pair_paths(service.devices)))


def count_paths(service: ServiceRow, out_of_service: Collection[str]) -> int:
    """The service's paths with no device named in `out_of_service`."""
    return sum(1 for path in paths(service) if not path.names & set(out_of_service))


def paths_up(service: ServiceRow) -> int:
    """The service's paths with no device out of service, by the statuses of its devices."""
    return count_paths(service, {device.name for device in service.out_of_service_devices})


def service_status(service: ServiceRow, paths_on_main: int, paths_during_change: int) -> ImpactStatus | None:
    """ "down" with no path left, "at risk" with fewer paths than on main but at least 1, otherwise None.

    A service with no path on main and none during the change is down only when a device behind it is out of
    service; a service with no device pair at all, such as one whose order has not run yet, is not affected.
    """
    if paths_during_change == 0:
        return STATUS_DOWN if paths_on_main > 0 or service.affected else None
    if paths_during_change < paths_on_main:
        return STATUS_AT_RISK
    return None


def service_impacts(active: Iterable[ServiceRow], main_data: Mapping[str, object]) -> tuple[ServiceImpact, ...]:
    """Each active service that is at risk or down during the change, compared with main.

    A service missing on main counts every device pair behind it as a path on main.
    """
    main_services = {service.identifier: service for service in parse_services(main_data)}
    impacts = []
    for service in active:
        on_main = main_services.get(service.identifier)
        main_count = len(paths(service)) if on_main is None else paths_up(on_main)
        during = paths_up(service)
        status = service_status(service, main_count, during)
        if status is not None:
            impacts.append(
                ServiceImpact(service=service, paths_on_main=main_count, paths_during_change=during, status=status)
            )
    return tuple(impacts)


# Formatting


def format_bandwidth(mbps: int | None) -> str:
    return f"{mbps:,} Mbps" if mbps is not None else NOT_SET


def join_names(names: Iterable[str]) -> str:
    """Join names in name order: "A", "A and B", "A, B and C"."""
    ordered = sorted(names)
    if len(ordered) <= 1:
        return "".join(ordered)
    return f"{', '.join(ordered[:-1])} and {ordered[-1]}"


def _gold_phrase(impacts: list[ServiceImpact]) -> str:
    """ "2 Gold services for Northbank" or "2 Gold services": only real customers are named."""
    noun = "service" if len(impacts) == 1 else "services"
    names = join_names({impact.service.customer for impact in impacts if impact.service.customer})
    return f"{len(impacts)} Gold {noun} for {names}" if names else f"{len(impacts)} Gold {noun}"


# Figures


def headline_text(impacts: Iterable[ServiceImpact]) -> str:
    """Headline for the active services of the selected change: Gold services down first, then at risk."""
    impacts = tuple(impacts)
    if not impacts:
        return NO_SERVICE_AFFECTED
    gold_down = [impact for impact in impacts if impact.service.gold and impact.status == STATUS_DOWN]
    if gold_down:
        verb = "has" if len(gold_down) == 1 else "have"
        return f"{_gold_phrase(gold_down)} {verb} no path during this change"
    gold_at_risk = [impact for impact in impacts if impact.service.gold]
    if gold_at_risk:
        verb = "has" if len(gold_at_risk) == 1 else "have"
        return f"{_gold_phrase(gold_at_risk)} {verb} fewer separate paths during this change"
    if len(impacts) == 1:
        return "1 service is affected by this change, and it is not Gold"
    return f"{len(impacts)} services are affected by this change, and none of them is Gold"


def headline_caption(change_label: str, result: BlastRadius) -> str:
    """Caption under the headline; empty for "Current network", which is no proposed change."""
    if change_label == CURRENT_NETWORK:
        return ""
    if result.gold_headline:
        return f"{change_label} · found in a proposed change, before merge"
    return f"{change_label} · seen in a proposed change, before merge"


def tiles(impacts: Iterable[ServiceImpact]) -> tuple[Tile, ...]:
    impacts = tuple(impacts)
    customers = {impact.service.customer for impact in impacts if impact.service.customer}
    gold_at_risk = sum(1 for impact in impacts if impact.service.gold and impact.status == STATUS_AT_RISK)
    down = sum(1 for impact in impacts if impact.status == STATUS_DOWN)
    return (
        Tile(TILE_CUSTOMERS, str(len(customers)), HELP_CUSTOMERS, COUNTED),
        Tile(TILE_GOLD_AT_RISK, str(gold_at_risk), HELP_GOLD_AT_RISK, COUNTED),
        Tile(TILE_DOWN, str(down), HELP_DOWN, COUNTED),
    )


def affected_service_rows(impacts: Iterable[ServiceImpact], rules: Mapping[str, int]) -> tuple[AffectedServiceRow, ...]:
    return tuple(
        AffectedServiceRow(
            service=impact.service.identifier,
            customer=impact.service.customer_label,
            tier=impact.service.tier_label,
            bandwidth=format_bandwidth(impact.service.bandwidth_mbps),
            switch=impact.service.device_label(CORE_ROLE),
            edge_router=impact.service.device_label(EDGE_ROLE),
            paths_on_main=impact.paths_on_main,
            paths_during_change=impact.paths_during_change,
            status=impact.status,
            rule=rules.get(impact.service.tier or "", 0),
        )
        for impact in impacts
    )


def build_blast_radius(data: Mapping[str, object], main_data: Mapping[str, object]) -> BlastRadius:
    """All figures of the Planned maintenance page from the query on the selected branch and on main."""
    active = active_services(parse_services(data))
    if not active:
        return BlastRadius(
            no_services=True, headline=NO_SERVICES_FOUND, gold_headline=False, tiles=(), affected_rows=()
        )
    impacts = service_impacts(active, main_data)
    return BlastRadius(
        no_services=False,
        headline=headline_text(impacts),
        gold_headline=any(impact.service.gold for impact in impacts),
        tiles=tiles(impacts),
        affected_rows=affected_service_rows(impacts, tier_rules(data)),
    )


# Proposed change picker


def picker_entries(proposed_changes: Iterable[Mapping[str, object]]) -> tuple[PickerEntry, ...]:
    """ "Current network" first, then open proposed changes in name order, without order requests.

    Each dict carries `name`, `source_branch`, optional `state` and `tags` (tag names).
    """
    entries = []
    for change in proposed_changes:
        name, branch, tags = change.get("name"), change.get("source_branch"), change.get("tags")
        if not isinstance(name, str) or not isinstance(branch, str):
            continue
        if change.get("state", "open") != "open":
            continue
        if isinstance(tags, (list, tuple, set)) and SERVICE_REQUEST_TAG in tags:
            continue
        entries.append(PickerEntry(name, branch))
    entries.sort(key=lambda entry: entry.label)
    return (PickerEntry(CURRENT_NETWORK, MAIN_BRANCH), *entries)


def default_picker_index(entries: tuple[PickerEntry, ...]) -> int:
    """Index of "Paris router 1 maintenance", or 0 ("Current network") when it is not listed."""
    return next((index for index, entry in enumerate(entries) if entry.label == DEFAULT_CHANGE), 0)
