"""The affected customers of a proposed change, and the outreach payload for the CRM.

Plain functions over the `data` dict that the stored query
`business_impact_services` returns, on the proposed change's branch and on
main, and the Gold outage guard's result for that change. The affected
customers transform (`transforms/affected_customers.py`) turns them into the
"Affected customers" artifact, and the outreach transform
(`transforms/outreach_payload.py`) into the body the webhook sends to the CRM.

Which services are at risk or down comes from `blast_radius.service_impacts`,
and whether the change is blocked comes from the guard's result
(`gold_outage_guard.evaluate`). Nothing here counts paths or applies the rule
again.

Each affected service gets a status:

- a Gold service with at least one path left, in a change the guard passes:
  "at risk, notified". It is the only status the webhook sends to the CRM.
- a Gold service in a change the guard blocks: "down, change blocked" (or
  "at risk, change blocked" when it keeps a path), because the webhook
  notifies no one for a blocked change.
- any other service: "down, not notified" (or "at risk, not notified").

The output holds customer names, tiers and service identifiers only, never a
contact detail. The CRM maps a customer and a tier to its contacts.

The imports are relative on purpose: the Infrahub task worker imports this
module from the commit worktree as `commits.<sha>.service_catalog...`, where an
absolute `service_catalog` import does not resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

from .blast_radius import GOLD, STATUS_DOWN, active_services, parse_services, service_impacts, tier_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .blast_radius import ImpactStatus
    from .gold_outage_guard import GuardResult

# Each status is the service's status during the change, then whether its customer is notified.
NotificationStatus = Literal[
    "at risk, notified",
    "down, change blocked",
    "at risk, change blocked",
    "down, not notified",
    "at risk, not notified",
]
STATUS_AT_RISK_NOTIFIED: Final = "at risk, notified"
STATUS_DOWN_NOT_NOTIFIED: Final = "down, not notified"
STATUS_DOWN_CHANGE_BLOCKED: Final = "down, change blocked"
STATUS_AT_RISK_CHANGE_BLOCKED: Final = "at risk, change blocked"
STATUS_AT_RISK_NOT_NOTIFIED: Final = "at risk, not notified"

# When the services of one customer and tier have different statuses, the row takes the first one in
# this list: a customer the CRM notifies shows as notified, and "down" comes before "at risk". The
# Customer notification page lists the status groups in the same order.
STATUS_ORDER: tuple[NotificationStatus, ...] = (
    STATUS_AT_RISK_NOTIFIED,
    STATUS_DOWN_CHANGE_BLOCKED,
    STATUS_AT_RISK_CHANGE_BLOCKED,
    STATUS_DOWN_NOT_NOTIFIED,
    STATUS_AT_RISK_NOT_NOTIFIED,
)

PAYLOAD_SOURCE = "infrahub"
# The artifact field that names the branch the artifact was generated on.
BRANCH_KEY = "branch"


@dataclass(frozen=True)
class AffectedCustomer:
    """One customer and tier affected by a change: its affected services and its status.

    `notified_services` are the services the webhook sends to the CRM: the Gold services that keep at
    least one path in a change the guard passes.
    """

    customer: str
    tier: str
    services: tuple[str, ...]
    status: NotificationStatus
    notified_services: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """The artifact row: customer, tier, services and status."""
        return {"customer": self.customer, "tier": self.tier, "services": list(self.services), "status": self.status}


def service_notification_status(tier: str | None, impact_status: ImpactStatus, blocked: bool) -> NotificationStatus:
    """The notification status of one affected service, from its tier, its status during the change and the verdict."""
    down = impact_status == STATUS_DOWN
    if tier == GOLD and blocked:
        return STATUS_DOWN_CHANGE_BLOCKED if down else STATUS_AT_RISK_CHANGE_BLOCKED
    if tier == GOLD and not down:
        return STATUS_AT_RISK_NOTIFIED
    return STATUS_DOWN_NOT_NOTIFIED if down else STATUS_AT_RISK_NOT_NOTIFIED


def status_key(status: str) -> tuple[int, str]:
    """Sort key for statuses in `STATUS_ORDER`. A status read from an artifact that is not in it comes last."""
    return (STATUS_ORDER.index(status) if status in STATUS_ORDER else len(STATUS_ORDER), status)


def affected_customers(
    branch_data: Mapping[str, object], main_data: Mapping[str, object], guard_result: GuardResult
) -> list[AffectedCustomer]:
    """Each customer and tier with an active service at risk or down on the branch, compared with main.

    One row per customer and tier, Gold first, then Silver, Bronze, any other tier, then by customer name.
    A customer with Gold and Silver services affected has one row per tier.
    """
    blocked = not guard_result.passed
    impacts = service_impacts(active_services(parse_services(branch_data)), main_data)
    grouped: dict[tuple[str, str], list[tuple[str, NotificationStatus]]] = {}
    for impact in impacts:
        service = impact.service
        status = service_notification_status(service.tier, impact.status, blocked)
        grouped.setdefault((service.customer_label, service.tier_label), []).append((service.identifier, status))

    rows = [
        AffectedCustomer(
            customer=customer,
            tier=tier,
            services=tuple(sorted(identifier for identifier, _ in services)),
            status=min((status for _, status in services), key=STATUS_ORDER.index),
            notified_services=tuple(
                sorted(identifier for identifier, status in services if status == STATUS_AT_RISK_NOTIFIED)
            ),
        )
        for (customer, tier), services in grouped.items()
    ]
    return sorted(rows, key=lambda row: (*tier_key(row.tier), row.customer))


def affected_customers_report(
    branch: str, affected: Iterable[AffectedCustomer], guard_result: GuardResult
) -> dict[str, Any]:
    """The "Affected customers" artifact: the branch, whether the guard blocks the change, and each row."""
    return {
        BRANCH_KEY: branch,
        "blocked": not guard_result.passed,
        "customers": [row.as_dict() for row in affected],
    }


def outreach_payload(
    change_id: str,
    change_name: str,
    source_branch: str,
    affected: Iterable[AffectedCustomer],
    guard_result: GuardResult,
) -> dict[str, Any]:
    """The body the outreach webhook sends to the CRM for a new proposed change.

    It lists the Gold customers whose services keep at least one path, by customer name, with only
    those services. When the guard blocks the change, `blocked` is true and no customer is listed.
    Silver and Bronze customers are never listed.
    """
    blocked = not guard_result.passed
    customers = (
        []
        if blocked
        else [
            {"customer": row.customer, "tier": row.tier, "services": list(row.notified_services)}
            for row in sorted(affected, key=lambda row: row.customer)
            if row.tier == GOLD and row.notified_services
        ]
    )
    return {
        "source": PAYLOAD_SOURCE,
        "proposed_change": {"id": change_id, "name": change_name, "source_branch": source_branch},
        "blocked": blocked,
        "customers": customers,
    }
