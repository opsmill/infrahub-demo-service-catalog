"""Figures for the Blast radius view.

Plain functions over the `data` dict that the stored query
`business_impact_services` returns. The page runs the query on the selected
branch and again on main (the main read uses its `DcimDevice` block), reads the Gold
SLA credit percentage from its `ServiceTier` block, then calls
`build_blast_radius`. Nothing here imports Streamlit or writes to Infrahub,
so every figure on the page is unit-tested offline.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CURRENT_NETWORK = "Current network"
MAIN_BRANCH = "main"
DEFAULT_CHANGE = "Paris router 1 maintenance"
SERVICE_REQUEST_TAG = "service_request"

ACTIVE = "active"
GOLD = "Gold"
CORE_ROLE = "core"
EDGE_ROLE = "edge"
UNASSIGNED = "Unassigned"
NOT_SET = "Not set"

NO_SERVICES_FOUND = "No services were found"
NO_SERVICE_AFFECTED = "No service is affected"
IN_THIS_CHANGE = "In this change"
SEGMENT_AFFECTED = "Affected"
SEGMENT_NOT_AFFECTED = "Not affected"

TILE_CUSTOMERS = "Customers affected"
TILE_GOLD = "Gold services affected"
TILE_CREDIT = "Gold SLA credit exposure, per month"
COUNTED = "Counted"
YOUR_INPUT = "Your input"


@dataclass(frozen=True)
class DeviceRow:
    """A device as the query reads it, behind a service or in the `DcimDevice` block."""

    name: str
    description: str | None
    role: str | None
    status: str | None
    site: str | None = None

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
    monthly_charge: int | None
    site: str | None
    customer: str | None
    tier: str | None
    sla_credit_pct: int | None
    devices: tuple[DeviceRow, ...]

    @property
    def active(self) -> bool:
        return self.status == ACTIVE

    @property
    def out_of_service_devices(self) -> tuple[DeviceRow, ...]:
        """The devices behind the service's dedicated interfaces that are not active."""
        return tuple(device for device in self.devices if device.out_of_service)

    @property
    def affected(self) -> bool:
        """True when any device behind the service's dedicated interfaces is not active."""
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

    @property
    def annual_contract_value(self) -> int:
        """Monthly charge x 12; a missing charge counts as 0."""
        return (self.monthly_charge or 0) * 12

    @property
    def monthly_sla_credit(self) -> Decimal:
        """Monthly charge x the tier's SLA credit percentage / 100; missing values count as 0."""
        return Decimal((self.monthly_charge or 0) * (self.sla_credit_pct or 0)) / 100

    def device_label(self, role: str) -> str:
        """Friendly name of the device with `role` behind the service, or "Not set"."""
        labels = sorted({device.label for device in self.devices if device.role == role})
        return ", ".join(labels) if labels else NOT_SET


@dataclass(frozen=True)
class Tile:
    label: str
    value: str
    help: str
    marker: str  # Counted or Your input, shown under the tile


@dataclass(frozen=True)
class CustomerValue:
    """One bar of the per-customer chart: annual contract value and its affected part."""

    customer: str
    annual: int
    affected_annual: int


@dataclass(frozen=True)
class ChartSegment:
    """One stacked segment of a customer's bar: the affected or the not-affected part."""

    customer: str
    segment: str
    annual: int


@dataclass(frozen=True)
class AffectedServiceRow:
    """One row of the "Affected services" table, already formatted for display."""

    service: str
    customer: str
    tier: str
    bandwidth: str
    switch: str
    edge_router: str
    monthly_charge: str


@dataclass(frozen=True)
class RouterRank:
    """One edge router in the ranking by Gold annual contract value."""

    name: str
    label: str
    gold_annual: int
    in_this_change: bool


@dataclass(frozen=True)
class BlastRadius:
    """Everything the Blast radius view shows for one selected change."""

    no_services: bool
    headline: str
    gold_headline: bool
    tiles: tuple[Tile, ...]
    customer_values: tuple[CustomerValue, ...]
    affected_rows: tuple[AffectedServiceRow, ...]
    routers: tuple[RouterRank, ...]


@dataclass(frozen=True)
class PickerEntry:
    label: str
    branch: str


# Parsing the query `data`


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _edges(container: object) -> list[Mapping[str, object]]:
    edges = _mapping(container).get("edges")
    if not isinstance(edges, list):
        return []
    return [_mapping(_mapping(edge).get("node")) for edge in edges]


def _peer(node: Mapping[str, object], name: str) -> Mapping[str, object]:
    return _mapping(_mapping(node.get(name)).get("node"))


def _attr(node: Mapping[str, object], name: str) -> object:
    return _mapping(node.get(name)).get("value")


def _text(node: Mapping[str, object], name: str) -> str | None:
    value = _attr(node, name)
    return str(value) if value not in {None, ""} else None


def _integer(node: Mapping[str, object], name: str) -> int | None:
    value = _attr(node, name)
    if isinstance(value, bool) or value in {None, ""}:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return None


def _device(node: Mapping[str, object]) -> DeviceRow | None:
    name = _text(node, "name")
    if name is None:
        return None
    return DeviceRow(
        name=name,
        description=_text(node, "description"),
        role=_text(node, "role"),
        status=_text(node, "status"),
        site=_text(_peer(node, "location"), "shortname"),
    )


def parse_services(data: Mapping[str, object]) -> tuple[ServiceRow, ...]:
    """Read every service of the query, in service identifier order."""
    services = []
    for node in _edges(data.get("ServiceDedicatedInternet")):
        identifier = _text(node, "service_identifier")
        if identifier is None:
            continue
        tier = _peer(node, "tier")
        devices = tuple(
            device
            for interface in _edges(node.get("dedicated_interfaces"))
            if (device := _device(_peer(interface, "device"))) is not None
        )
        services.append(
            ServiceRow(
                identifier=identifier,
                status=_text(node, "status"),
                bandwidth_mbps=_integer(node, "bandwidth"),
                monthly_charge=_integer(node, "monthly_charge"),
                site=_text(_peer(node, "location"), "shortname"),
                customer=_text(_peer(node, "customer"), "name"),
                tier=_text(tier, "name"),
                sla_credit_pct=_integer(tier, "sla_credit_pct"),
                devices=devices,
            )
        )
    return tuple(sorted(services, key=lambda service: service.identifier))


def parse_devices(data: Mapping[str, object]) -> tuple[DeviceRow, ...]:
    """Read the `DcimDevice` block of the query (on the selected branch or on main)."""
    return tuple(device for node in _edges(data.get("DcimDevice")) if (device := _device(node)) is not None)


def active_services(services: Iterable[ServiceRow]) -> tuple[ServiceRow, ...]:
    return tuple(service for service in services if service.active)


# Formatting


def format_eur(amount: float | Decimal) -> str:
    """Whole euros with thousands separators, for example "€2,565"."""
    rounded = Decimal(str(amount)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f"€{int(rounded):,}"


def format_bandwidth(mbps: int | None) -> str:
    return f"{mbps:,} Mbps" if mbps is not None else NOT_SET


def format_monthly_charge(charge: int | None) -> str:
    return format_eur(charge) if charge is not None else NOT_SET


def join_names(names: Iterable[str]) -> str:
    """Join names in name order: "A", "A and B", "A, B and C"."""
    ordered = sorted(names)
    if len(ordered) <= 1:
        return "".join(ordered)
    return f"{', '.join(ordered[:-1])} and {ordered[-1]}"


# Figures


def headline_text(active: Iterable[ServiceRow]) -> str:
    """Headline for the active services of the selected change."""
    active = tuple(active)
    if not active:
        return NO_SERVICES_FOUND
    affected = [service for service in active if service.affected]
    if not affected:
        return NO_SERVICE_AFFECTED
    gold = [service for service in affected if service.gold]
    if gold:
        noun, verb = ("service", "has") if len(gold) == 1 else ("services", "have")
        # Only real customers are named; a Gold service with no customer is counted but not named.
        names = join_names({service.customer for service in gold if service.customer})
        if not names:
            return f"{len(gold)} Gold {noun} {verb} no other path during this change"
        return f"{len(gold)} Gold {noun} for {names} {verb} no other path during this change"
    if len(affected) == 1:
        return "1 service has no other path during this change, and it is not Gold"
    return f"{len(affected)} services have no other path during this change, and none of them is Gold"


def headline_caption(change_label: str, result: BlastRadius) -> str:
    """Caption under the headline; empty for "Current network", which is no proposed change."""
    if change_label == CURRENT_NETWORK:
        return ""
    if result.gold_headline:
        return f"{change_label} · found in a proposed change, before merge"
    return f"{change_label} · seen in a proposed change, before merge"


def gold_credit_pct(data: Mapping[str, object]) -> int | None:
    """SLA credit percentage of the Gold tier node, from the `ServiceTier` block of the query.

    None when no tier is named Gold, so the help text reads "Not set".
    """
    return next(
        (_integer(node, "sla_credit_pct") for node in _edges(data.get("ServiceTier")) if _text(node, "name") == GOLD),
        None,
    )


def tiles(active: Iterable[ServiceRow], gold_pct: int | None) -> tuple[Tile, ...]:
    active = tuple(active)
    affected = [service for service in active if service.affected]
    customers = {service.customer for service in affected if service.customer}
    gold_total = sum(1 for service in active if service.gold)
    gold_affected = [service for service in affected if service.gold]
    credit = sum((service.monthly_sla_credit for service in gold_affected), Decimal(0))
    pct_text = f"{gold_pct}%" if gold_pct is not None else NOT_SET
    return (
        Tile(TILE_CUSTOMERS, str(len(customers)), COUNTED, COUNTED),
        Tile(TILE_GOLD, f"{len(gold_affected)} of {gold_total}", COUNTED, COUNTED),
        Tile(TILE_CREDIT, format_eur(credit), f"{YOUR_INPUT}. Gold tier credit: {pct_text}", YOUR_INPUT),
    )


def customer_values(active: Iterable[ServiceRow]) -> tuple[CustomerValue, ...]:
    """Annual contract value per customer and its affected part; "Unassigned" last."""
    annual: dict[str, int] = {}
    affected: dict[str, int] = {}
    for service in active:
        name = service.customer_label
        annual[name] = annual.get(name, 0) + service.annual_contract_value
        affected[name] = affected.get(name, 0) + (service.annual_contract_value if service.affected else 0)
    order = sorted(annual, key=lambda name: (name == UNASSIGNED, name))
    return tuple(CustomerValue(name, annual[name], affected[name]) for name in order)


def chart_segments(values: Iterable[CustomerValue]) -> tuple[ChartSegment, ...]:
    """Split each customer's annual contract value into its affected and not-affected parts, in bar order."""
    segments: list[ChartSegment] = []
    for value in values:
        segments.extend(
            (
                ChartSegment(value.customer, SEGMENT_AFFECTED, value.affected_annual),
                ChartSegment(value.customer, SEGMENT_NOT_AFFECTED, value.annual - value.affected_annual),
            )
        )
    return tuple(segments)


def affected_service_rows(active: Iterable[ServiceRow]) -> tuple[AffectedServiceRow, ...]:
    return tuple(
        AffectedServiceRow(
            service=service.identifier,
            customer=service.customer_label,
            tier=service.tier_label,
            bandwidth=format_bandwidth(service.bandwidth_mbps),
            switch=service.device_label(CORE_ROLE),
            edge_router=service.device_label(EDGE_ROLE),
            monthly_charge=format_monthly_charge(service.monthly_charge),
        )
        for service in active
        if service.affected
    )


def router_ranking(
    active: Iterable[ServiceRow],
    devices: Iterable[DeviceRow],
    main_devices: Iterable[DeviceRow],
) -> tuple[RouterRank, ...]:
    """Edge routers at sites with an active service, by Gold annual contract value.

    The value counts every active Gold service with an interface on the router,
    whatever the selected change, so only the "In this change" marker moves
    between changes. Ties go to the router whose first active service has the
    lowest service identifier, then to the router name.
    """
    active = tuple(active)
    sites = {service.site for service in active if service.site}
    main_status = {device.name: device.status for device in main_devices}
    ranks: list[tuple[int, str, RouterRank]] = []
    for router in devices:
        if router.role != EDGE_ROLE or router.site not in sites:
            continue
        on_router = [service for service in active if any(device.name == router.name for device in service.devices)]
        gold_annual = sum(service.annual_contract_value for service in on_router if service.gold)
        first_service = min((service.identifier for service in on_router), default="￿")
        changed = router.name not in main_status or main_status[router.name] != router.status
        ranks.append((gold_annual, first_service, RouterRank(router.name, router.label, gold_annual, changed)))
    ranks.sort(key=lambda item: (-item[0], item[1], item[2].name))
    return tuple(rank for _, _, rank in ranks)


def build_blast_radius(data: Mapping[str, object], main_data: Mapping[str, object]) -> BlastRadius:
    """All figures of the Blast radius view from the query on the selected branch and on main."""
    services = parse_services(data)
    active = active_services(services)
    headline = headline_text(active)
    if not active:
        return BlastRadius(True, headline, False, (), (), (), ())
    return BlastRadius(
        no_services=False,
        headline=headline,
        gold_headline=any(service.affected and service.gold for service in active),
        tiles=tiles(active, gold_credit_pct(data)),
        customer_values=customer_values(active),
        affected_rows=affected_service_rows(active),
        routers=router_ranking(active, parse_devices(data), parse_devices(main_data)),
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
