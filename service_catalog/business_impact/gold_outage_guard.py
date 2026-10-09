"""The Gold outage guard rule.

`checks/gold_outage_guard.py` runs the stored query `business_impact_services`
on the proposed change's branch and on main. For each active service whose
tier has a rule and each device that is not active on the branch
(`traversal_pairs`), it asks
Infrahub's path traversal whether a network path joins the two, then calls
`evaluate` with the devices each service reaches. The rule reuses the parsing
and the "out of service = device not active" rule of `blast_radius.py`.

The traversal only passes through `NETWORK_KINDS` and at most `MAX_HOPS`
relationships: service, interface, device. That is the same dependency the
Blast radius view reads from the query, so the view and the check agree. A
model where a service depends on devices further away (an access switch and
its uplinks, or a second path) raises `MAX_HOPS` and adds the link kinds,
without a new query.

Each service tier carries a rule, `min_paths`: the separate paths each of its
active services must keep during a change. An empty value counts as 0, and a
tier with rule 0 is never checked. With the seeded values only Gold has a rule
(1). `path_count` counts a service's separate paths: 1 when a switch and an
edge router sit behind its dedicated interfaces and none of the devices it
depends on is out of service, otherwise 0. The demo model has at most one path
per service. A deleted device, switch port or gateway interface removes a role,
so the service has 0 paths.

A change fails when an active service has fewer separate paths on the branch
than its tier's rule on the branch, and had at least as many on main as the
rule on main required. A service that does not exist on main counts as meeting
the rule on main. A service already short of its rule on main gives a warning,
not an error, so an existing problem does not block unrelated work. Nothing
here imports Streamlit or calls Infrahub.

The imports are relative on purpose: the Infrahub task worker imports this
module from the commit worktree as `commits.<sha>.service_catalog...`, where an
absolute `service_catalog` import does not resolve (see the check file).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import TYPE_CHECKING

from .blast_radius import (
    CORE_ROLE,
    EDGE_ROLE,
    GOLD,
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
    """An active service whose tier has a rule and a device that is not active on the branch: the path to look for."""

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


def tier_rules(data: Mapping[str, object]) -> dict[str, int]:
    """Each tier's minimum separate paths during a change, by tier name, from the `ServiceTier` block.

    An empty or unreadable value counts as 0. A tier that is not in the block is not in the result.
    """
    rules: dict[str, int] = {}
    for node in _edges(data, "ServiceTier"):
        name = _value(node, "name")
        if name in {None, ""}:
            continue
        value = _value(node, "min_paths")
        rules[str(name)] = value if isinstance(value, int) and not isinstance(value, bool) else 0
    return rules


def path_count(service: ServiceRow, dependent: Iterable[DeviceRow]) -> int:
    """The service's separate paths during the change: 1 or 0, as the demo model has at most one path.

    `service` is the row as the query returns it, before path traversal replaces its devices, so the roles
    behind its dedicated interfaces are known. `dependent` is the devices the service depends on. The service
    has 1 path when a switch and an edge router sit behind it and no device in `dependent` is out of service.
    """
    roles = {device.role for device in service.devices}
    if CORE_ROLE not in roles or EDGE_ROLE not in roles:
        return 0
    return 0 if any(device.out_of_service for device in dependent) else 1


def _tier_order(tier: str) -> tuple[bool, str]:
    """Gold first, then the other tiers in name order."""
    return (tier != GOLD, tier)


def traversal_pairs(branch_data: Mapping[str, object]) -> list[TraversalPair]:
    """Each active service whose tier rule on the branch is above 0, paired with each core or edge device
    that is not active on the branch.

    Services of a tier with rule 0 are left out, because no path count can fail them.
    """
    rules = tier_rules(branch_data)
    checked = {
        service.identifier
        for service in active_services(parse_services(branch_data))
        if service.tier is not None and rules.get(service.tier, 0) > 0
    }
    services = [
        (str(_value(node, "service_identifier")), str(node.get("id")))
        for node in _edges(branch_data, "ServiceDedicatedInternet")
        if _value(node, "service_identifier") in checked and node.get("id")
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
    """What the check logs: each error fails it; each warning and the summary are informational."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Logged when the check passes with no warning, so the check result records the exposure at approval time.
    summary: str | None = None

    @property
    def passed(self) -> bool:
        return not self.errors


def move_to_device(device: DeviceRow, devices: Iterable[DeviceRow]) -> DeviceRow | None:
    """The active device with the same role at the same site and the other index, or None.

    Each seeded site has two devices per role (index 1 and 2), so the other
    index is the other device of that role at that site; the first by name
    wins if a site ever has more. A device that is not active is no place to
    move a service to, so it is never returned.
    """
    if not device.site:
        return None
    peers = [
        other
        for other in devices
        if other.name != device.name
        and other.role == device.role
        and other.site == device.site
        and not other.out_of_service
    ]
    return min(peers, key=lambda other: other.name, default=None)


def _already_out(device: DeviceRow, main_devices: Mapping[str, DeviceRow]) -> bool:
    on_main = main_devices.get(device.name)
    return on_main is not None and on_main.out_of_service


def removed_devices(service: ServiceRow, main_services: Mapping[str, ServiceRow]) -> tuple[DeviceRow, ...]:
    """The devices the service had on main in a role it has no device for on the branch.

    `service` is the row the query returns on the branch, before path traversal replaces its devices.
    A role is still covered when the branch has any device of that role behind the service, so moving
    a service to the other edge router is not a removal.
    """
    on_main = main_services.get(service.identifier)
    if on_main is None:
        return ()
    roles = {device.role for device in service.devices}
    return tuple(device for device in on_main.devices if device.role not in roles)


def _caused_by_change(
    service: ServiceRow, removed: Iterable[DeviceRow], main_devices: Mapping[str, DeviceRow]
) -> tuple[DeviceRow, ...]:
    return tuple(
        device for device in (*service.out_of_service_devices, *removed) if not _already_out(device, main_devices)
    )


def _paths(count: int) -> str:
    return f"{count} separate path" if count == 1 else f"{count} separate paths"


def _rule_sentence(tier: str, need: int, left: int) -> str:
    return f"{tier} requires at least {_paths(need)} during a change, and this change leaves {left}."


@dataclass
class _ShortTier:
    """The services of one tier that the change leaves short of the tier's rule on the branch."""

    tier: str
    need: int
    # Each service with its path count on the branch.
    services: list[tuple[ServiceRow, int]] = field(default_factory=list)
    # The devices the change takes out of service or removes behind those services.
    devices_out: list[DeviceRow] = field(default_factory=list)


def _error_message(
    change_name: str, short: _ShortTier, branch_devices: tuple[DeviceRow, ...], main_devices: Mapping[str, DeviceRow]
) -> str:
    services = [service for service, _ in short.services]
    left = min(count for _, count in short.services)
    one = len(services) == 1
    noun = "service" if one else "services"
    names = join_names({service.customer for service in services if service.customer})
    customers = f" for {names}" if names else ""
    identifiers = ", ".join(service.identifier for service in services)
    credit = sum((service.monthly_sla_credit for service in services), Decimal(0))
    without = "with no other path" if left == 0 else f"with fewer separate paths than the {short.tier} rule requires"

    # Devices behind a service carry no site in the query; the `DcimDevice` block does. A device the change
    # deleted is only in the block on main.
    by_name = {**main_devices, **{device.name: device for device in branch_devices}}
    unique: list[DeviceRow] = []
    for device in short.devices_out:
        if all(seen.name != device.name for seen in unique):
            unique.append(by_name.get(device.name) or device)
    targets = [move_to_device(device, branch_devices) for device in unique]
    pronoun = "this service" if one else "these services"
    if all(target is not None for target in targets):
        action = f"Move {pronoun} to {join_names({target.label for target in targets if target is not None})} first."
    else:
        action = f"Move {pronoun} off {join_names({device.label for device in unique})} first."

    return (
        f"{change_name} leaves {len(services)} {short.tier} {noun}{customers} {without} ({identifiers}). "
        f"{short.tier} SLA credit exposure: {format_eur(credit)} per month ({CREDIT_LABEL}). "
        f"{action} {_rule_sentence(short.tier, short.need, left)}"
    )


def _warning_message(service: ServiceRow, devices_out: Iterable[DeviceRow]) -> str:
    devices = join_names({device.label for device in devices_out})
    behind = f", behind {devices}" if devices else ""
    return (
        f"WARNING: {service.tier_label} service {service.identifier} for {service.customer_label} is already out "
        f"of service on the current network{behind}. This change does not cause it, so it does not block the merge."
    )


@dataclass
class _Guard:
    """The branch and main as the rule compares them, and what it finds service by service."""

    branch_data: Mapping[str, object]
    main_data: Mapping[str, object]
    reached: Mapping[str, Collection[str]] | None
    short: dict[str, _ShortTier] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.branch_devices = parse_devices(self.branch_data)
        self.main_devices = {device.name: device for device in parse_devices(self.main_data)}
        self.main_services = {service.identifier: service for service in parse_services(self.main_data)}
        self.branch_rules = tier_rules(self.branch_data)
        self.main_rules = tier_rules(self.main_data)

    def needs(self, tier: str) -> tuple[int, int]:
        """The tier's rule on the branch and on main. A tier missing on one side uses the other side's rule."""
        need_b = self.branch_rules.get(tier, self.main_rules.get(tier, 0))
        return need_b, self.main_rules.get(tier, need_b)

    def depends_on(self, service: ServiceRow) -> ServiceRow:
        """The service with the devices it depends on: those path traversal reached, when it ran."""
        if self.reached is None:
            return service
        by_name = {device.name: device for device in self.branch_devices}
        names = sorted(self.reached.get(service.identifier, ()))
        return replace(service, devices=tuple(by_name[name] for name in names if name in by_name))

    def main_paths(self, service: ServiceRow, need_m: int) -> int:
        """The service's path count on main. A service missing on main meets the rule on main."""
        on_main = self.main_services.get(service.identifier)
        return need_m if on_main is None else path_count(on_main, on_main.devices)

    def check(self, service: ServiceRow, tier: str) -> None:
        need_b, need_m = self.needs(tier)
        depends_on = self.depends_on(service)
        # The roles come from the row as queried, before path traversal replaces its devices.
        paths_b = path_count(service, depends_on.devices)
        if paths_b >= need_b:
            return
        lost = removed_devices(service, self.main_services)
        if self.main_paths(service, need_m) < need_m:
            self.warnings.append(_warning_message(service, (*depends_on.out_of_service_devices, *lost)))
            return
        short = self.short.setdefault(tier, _ShortTier(tier, need_b))
        short.services.append((service, paths_b))
        caused = _caused_by_change(depends_on, lost, self.main_devices)
        short.devices_out.extend(caused or (*depends_on.out_of_service_devices, *lost))

    def errors(self, change_name: str) -> list[str]:
        """One message per tier with services short of the rule, Gold first, then the tiers in name order."""
        return [
            _error_message(change_name, self.short[tier], self.branch_devices, self.main_devices)
            for tier in sorted(self.short, key=_tier_order)
        ]


def evaluate(
    branch_data: Mapping[str, object],
    main_data: Mapping[str, object],
    change_name: str,
    reached: Mapping[str, Collection[str]] | None = None,
) -> GuardResult:
    """Apply the guard to the query result on the proposed change's branch and on main.

    For each active service with a tier, the rule on the branch and on main comes from `tier_rules`. A tier
    missing from one side's `ServiceTier` block uses the other side's rule, and a tier missing from both has
    rule 0. The path count on the branch comes from `path_count`; on main it uses the devices behind the
    service on main, and a service missing on main counts as meeting the rule on main.

    `reached` maps a service identifier to the names of the devices that path traversal reached from it.
    When it is given, those devices are the ones each service depends on; when it is None, the devices
    behind the service's interfaces in the query are. There is no override: no tag, setting or threshold
    changes the result.
    """
    guard = _Guard(branch_data, main_data, reached)
    for service in active_services(parse_services(branch_data)):
        if service.tier is not None:
            guard.check(service, service.tier)

    result = GuardResult(errors=guard.errors(change_name), warnings=guard.warnings)
    if not result.errors and not result.warnings:
        result.summary = (
            f"{change_name} leaves no active Gold service without a path. "
            f"Gold SLA credit exposure: {format_eur(Decimal(0))} per month ({CREDIT_LABEL})."
        )
    return result
