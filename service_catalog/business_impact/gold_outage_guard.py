"""The Gold outage guard rule.

`checks/gold_outage_guard.py` runs the stored query `business_impact_services`
on the proposed change's branch and on main, adds the footprint of each active
service on each side (`footprint.service_footprints`, Infrahub's path traversal
from the service through its interfaces to the core and edge devices at its
site), then calls `evaluate`. The devices in a service's footprint are the
devices the service depends on. The rule reuses the parsing and the "out of
service = device not active" rule of `blast_radius.py`, so the Planned
maintenance page and the check read the same dependency.

Each service tier carries a rule, `min_paths`: the separate paths each of its
active services must keep during a change. An empty value counts as 0, and a
tier with rule 0 is never checked. With the seeded values only Gold has a rule
(1). A separate path is the route through a switch and the edge router with the
same number at the same site, both in the service's footprint
(`blast_radius.paths`). `blast_radius.paths_up` counts the paths with no device that the
service depends on out of service. A deleted device, switch port or gateway
interface removes the paths it was on.

A change fails when an active service has fewer separate paths on the branch
than its tier's rule on the branch, and had at least as many on main as the
rule on main required. A service that does not exist on main counts as meeting
the rule on main. A service already short of its rule on main gives a warning,
not an error, so an existing problem does not block unrelated work. A change
that raises a tier's rule fails when an active service of that tier has fewer
separate paths on the branch than the new rule, in one tightening error per
tier; those services get no path error. A service with neither a switch nor an
edge router in its footprint on the branch and on main is left out: it has no path to
lose, and the change took none away. Nothing here imports Streamlit or calls
Infrahub.

The imports are relative on purpose: the Infrahub task worker imports this
module from the commit worktree as `commits.<sha>.service_catalog...`, where an
absolute `service_catalog` import does not resolve (see the check file).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..network import CORE_ROLE, EDGE_ROLE  # noqa: TID252 - the commit worktree import
from .blast_radius import (
    GOLD,
    DeviceRow,
    ServiceRow,
    active_services,
    join_names,
    parse_devices,
    parse_services,
    paths_up,
    tier_key,
    tier_rules,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


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

    `service` is the row `blast_radius.parse_services` reads on the branch.
    A role is still covered when the service's footprint on the branch has any device of that role, so moving
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


def _counts_sentence(services: list[tuple[ServiceRow, int, int | None]]) -> str:
    """The paths of each short service on the current network and during the change, in one sentence."""

    def counts(on_main: int | None, during: int) -> str:
        if on_main is None:
            return f"becomes active in this change and has {_paths(during)}"
        return f"has {_paths(on_main)} on the current network and {during} during this change"

    if len(services) == 1:
        _, during, on_main = services[0]
        return f"It {counts(on_main, during)}."
    if len({(during, on_main) for _, during, on_main in services}) == 1:
        _, during, on_main = services[0]
        return f"Each {counts(on_main, during)}."
    listed = "; ".join(f"{service.identifier} {counts(on_main, during)}" for service, during, on_main in services)
    return f"{listed}."


def _rule_sentence(tier: str, need: int, left: int) -> str:
    return f"{tier} requires at least {_paths(need)} during a change, and this change leaves {left}."


@dataclass
class _ShortTier:
    """The services of one tier that the change leaves short of the tier's rule on the branch."""

    tier: str
    need: int
    # Each service with its path count on the branch and on main (None when the service is not active on main).
    services: list[tuple[ServiceRow, int, int | None]] = field(default_factory=list)
    # The devices the change takes out of service or removes from the footprints of those services.
    devices_out: list[DeviceRow] = field(default_factory=list)


def _error_message(
    change_name: str, short: _ShortTier, branch_devices: tuple[DeviceRow, ...], main_devices: Mapping[str, DeviceRow]
) -> str:
    services = [service for service, _, _ in short.services]
    left = min(count for _, count, _ in short.services)
    one = len(services) == 1
    noun = "service" if one else "services"
    names = join_names({service.customer for service in services if service.customer})
    customers = f" for {names}" if names else ""
    identifiers = ", ".join(service.identifier for service in services)
    without = "with no other path" if left == 0 else f"with fewer separate paths than the {short.tier} rule requires"

    # Take each device from the `DcimDevice` block, on the branch or, for a device the change deleted, on main.
    by_name = {**main_devices, **{device.name: device for device in branch_devices}}
    unique: list[DeviceRow] = []
    for device in short.devices_out:
        if all(seen.name != device.name for seen in unique):
            unique.append(by_name.get(device.name) or device)
    targets = [move_to_device(device, branch_devices) for device in unique]
    pronoun = "this service" if one else "these services"
    # A service not active on main with an empty footprint has no device to name, so no Move sentence.
    action = ""
    if unique and all(target is not None for target in targets):
        action = f"Move {pronoun} to {join_names({target.label for target in targets if target is not None})} first. "
    elif unique:
        action = f"Move {pronoun} off {join_names({device.label for device in unique})} first. "

    return (
        f"{change_name} leaves {len(services)} {short.tier} {noun}{customers} {without} ({identifiers}). "
        f"{_counts_sentence(short.services)} {action}{_rule_sentence(short.tier, short.need, left)}"
    )


def _tightening_message(
    change_name: str, tier: str, old: int, new: int, services_with_counts: list[tuple[ServiceRow, int]]
) -> str:
    """The error for a change that raises the tier's rule from `old` to `new` while services have fewer paths."""
    one = len(services_with_counts) == 1
    noun = "service has" if one else "services have"
    counts = {count for _, count in services_with_counts}
    if not one and len(counts) == 1:
        listed = f"{', '.join(service.identifier for service, _ in services_with_counts)}: {counts.pop()} each"
    else:
        listed = ", ".join(f"{service.identifier}: {count}" for service, count in services_with_counts)
    return (
        f"{change_name} raises the {tier} rule from {old} to {_paths(new)} during a change, and "
        f"{len(services_with_counts)} active {tier} {noun} fewer ({listed}). "
        f"Build the paths first, or keep the rule at {old}."
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
    short: dict[str, _ShortTier] = field(default_factory=dict)
    # Each raised tier's services with fewer paths on the branch than the new rule, with their path counts.
    tightened: dict[str, list[tuple[ServiceRow, int]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Read from `branch_data` and `main_data` when the guard is built.
    branch_devices: tuple[DeviceRow, ...] = field(init=False)
    main_devices: dict[str, DeviceRow] = field(init=False)
    main_services: dict[str, ServiceRow] = field(init=False)
    branch_rules: dict[str, int] = field(init=False)
    main_rules: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        self.branch_devices = parse_devices(self.branch_data)
        self.main_devices = {device.name: device for device in parse_devices(self.main_data)}
        # Only services active on main: one that is new, draft or pending there has no paths to lose, so a
        # change that makes it active is checked against the branch rule, not reported as already down.
        self.main_services = {
            service.identifier: service for service in parse_services(self.main_data) if service.active
        }
        self.branch_rules = tier_rules(self.branch_data)
        self.main_rules = tier_rules(self.main_data)

    def needs(self, tier: str) -> tuple[int, int]:
        """The tier's rule on the branch and on main. A tier missing on one side uses the other side's rule."""
        need_b = self.branch_rules.get(tier, self.main_rules.get(tier, 0))
        return need_b, self.main_rules.get(tier, need_b)

    def main_paths(self, service: ServiceRow, need_m: int) -> int:
        """The service's path count on main. A service not active on main meets the rule on main."""
        on_main = self.main_services.get(service.identifier)
        return need_m if on_main is None else paths_up(on_main)

    def has_no_roles(self, service: ServiceRow) -> bool:
        """True when the service's footprint has neither a switch nor an edge router on the branch and on main.

        Such a service has no path to lose, and the change took none away, so the guard leaves it out.
        A service not active on main does not qualify: it is checked against the branch rule.
        """
        on_main = self.main_services.get(service.identifier)
        if on_main is None:
            return False
        return not any(device.role in {CORE_ROLE, EDGE_ROLE} for device in (*service.devices, *on_main.devices))

    def check(self, service: ServiceRow, tier: str) -> None:
        if self.has_no_roles(service):
            return
        need_b, need_m = self.needs(tier)
        paths_b = paths_up(service)
        if paths_b >= need_b:
            return
        if need_b > need_m:
            self.tightened.setdefault(tier, []).append((service, paths_b))
            return
        lost = removed_devices(service, self.main_services)
        paths_m = self.main_paths(service, need_m)
        if paths_m < need_m:
            self.warnings.append(_warning_message(service, (*service.out_of_service_devices, *lost)))
            return
        short = self.short.setdefault(tier, _ShortTier(tier, need_b))
        on_main = paths_m if service.identifier in self.main_services else None
        short.services.append((service, paths_b, on_main))
        caused = _caused_by_change(service, lost, self.main_devices)
        short.devices_out.extend(caused or (*service.out_of_service_devices, *lost))

    def errors(self, change_name: str) -> list[str]:
        """One path error per tier with services short of the rule, then one tightening error per raised tier.

        Each group lists Gold, Silver and Bronze first, then any other tier in name order.
        """
        path_errors = [
            _error_message(change_name, self.short[tier], self.branch_devices, self.main_devices)
            for tier in sorted(self.short, key=tier_key)
        ]
        tightening_errors = []
        for tier in sorted(self.tightened, key=tier_key):
            need_b, need_m = self.needs(tier)
            tightening_errors.append(_tightening_message(change_name, tier, need_m, need_b, self.tightened[tier]))
        return path_errors + tightening_errors


def evaluate(
    branch_data: Mapping[str, object],
    main_data: Mapping[str, object],
    change_name: str,
) -> GuardResult:
    """Apply the guard to the query result, with footprints, on the proposed change's branch and on main.

    For each active service with a tier, the rule on the branch and on main comes from `tier_rules`. A tier
    missing from one side's `ServiceTier` block uses the other side's rule, and a tier missing from both has
    rule 0. The path count on the branch comes from `blast_radius.paths_up`; on main it uses the footprint of the
    service on main, and a service not active on main counts as meeting the rule on main. When the branch raises
    a tier's rule, its services with fewer paths than the new rule go into one tightening error for the tier
    instead of a path error or a warning.

    Each service depends on the devices in its footprint (`footprint.with_footprints`). There is no override:
    no tag, setting or threshold changes the result.
    """
    guard = _Guard(branch_data, main_data)
    for service in active_services(parse_services(branch_data)):
        if service.tier is not None:
            guard.check(service, service.tier)

    errors = guard.errors(change_name)
    need_gold, _ = guard.needs(GOLD)
    summary = (
        None
        if errors or guard.warnings
        else f"{change_name} leaves every active Gold service with at least {_paths(need_gold)}."
    )
    return GuardResult(errors=errors, warnings=guard.warnings, summary=summary)
