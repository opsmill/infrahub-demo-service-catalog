"""What the Customer notification page shows: the affected customers, and the state of their file in Infrahub.

Plain functions over the proposed changes, the "Affected customers" content
and the stored artifact, so the page's choices are unit-tested without
Streamlit or a server.

The page shows the list it computes from the live data with
`change_impact.read_affected_report`, the function the affected customers
transform uses. It then compares that list with the artifact Infrahub stored on
the proposed change's branch. The stored artifact can be missing, still
generating, failed, unreadable, main's copy (its `branch` field is `main`,
because Infrahub has not generated the artifact on the branch yet) or older
than the live list, for example after a change merged into main. In each of
these cases the page says so and offers to generate the artifact again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from service_catalog.artifact_view import STALE

from .blast_radius import CURRENT_NETWORK, PickerEntry, picker_entries
from .notification import BRANCH_KEY, status_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

ARTIFACT_NAME = "affected-customers"
NOT_GENERATED = "The file in Infrahub for this change is not generated yet"
GENERATION_FAILED = (
    "Generation failed: Infrahub could not generate the file for this change. The task log has the details."
)
UNREADABLE = "The affected customers file in Infrahub could not be read"
NO_OPEN_CHANGE = "No proposed change is open"
NO_CUSTOMER_AFFECTED = "No customer is affected by this change"
BLOCKED_CAPTION = "The Gold outage guard blocks this change, so no customer is notified."


@dataclass(frozen=True)
class CustomerRow:
    customer: str
    tier: str
    services: str


@dataclass(frozen=True)
class StatusGroup:
    """The customers of one status, in the artifact's order (Gold first, then by name)."""

    status: str
    rows: tuple[CustomerRow, ...]


@dataclass(frozen=True)
class Notice:
    """A message about the file in Infrahub. `error` and `warning` set how the page shows it; otherwise information."""

    text: str
    error: bool = False
    warning: bool = False


@dataclass(frozen=True)
class NotificationList:
    """The artifact as the page shows it: whether the change is blocked, and the customers grouped by status."""

    blocked: bool
    groups: tuple[StatusGroup, ...]


def change_options(proposed_changes: Iterable[Mapping[str, object]]) -> tuple[PickerEntry, ...]:
    """Open proposed changes in name order, without service orders. The current network is no proposed change."""
    return tuple(entry for entry in picker_entries(proposed_changes) if entry.label != CURRENT_NETWORK)


def parse_artifact(content: str | Mapping[str, Any] | None) -> NotificationList | None:
    """The artifact content grouped by status, or None when there is no readable artifact."""
    if content is None:
        return None
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("customers"), list):
        return None

    grouped: dict[str, list[CustomerRow]] = {}
    for customer in data["customers"]:
        if not isinstance(customer, dict):
            continue
        services = customer.get("services") or []
        grouped.setdefault(str(customer.get("status", "")), []).append(
            CustomerRow(
                customer=str(customer.get("customer", "")),
                tier=str(customer.get("tier", "")),
                services=", ".join(str(service) for service in services),
            )
        )
    return NotificationList(
        blocked=bool(data.get("blocked")),
        groups=tuple(StatusGroup(status, tuple(grouped[status])) for status in sorted(grouped, key=status_key)),
    )


def status_heading(group: StatusGroup) -> str:
    """ "At risk, notified (2)": the status, capitalised, with its number of customers."""
    return f"{group.status[:1].upper()}{group.status[1:]} ({len(group.rows)})"


def _read_state(content: str | None, branch: str, *, failed: bool) -> tuple[NotificationList | Notice, Any]:
    """The state `notification_state` returns, with the parsed content when there is one."""
    if failed:
        return Notice(GENERATION_FAILED, error=True), None
    if content is None:
        return Notice(NOT_GENERATED), None
    try:
        data = json.loads(content)
    except ValueError:
        return Notice(UNREADABLE, error=True), None
    result = parse_artifact(data)
    if result is None:
        return Notice(UNREADABLE, error=True), data
    if data.get(BRANCH_KEY) != branch:
        return Notice(NOT_GENERATED), data
    return result, data


def notification_state(content: str | None, branch: str, *, failed: bool = False) -> NotificationList | Notice:
    """What the page shows for the artifact read on `branch`: the list, or a notice.

    `content` is the artifact content when the artifact is Ready, and None otherwise. `failed` is True when
    Infrahub could not generate the artifact. A list generated on another branch, such as main's copy, is
    not generated yet for this change.
    """
    return _read_state(content, branch, failed=failed)[0]


def file_notice(stored: str | None, live: Mapping[str, Any], branch: str, *, failed: bool = False) -> Notice | None:
    """What the page says about the artifact stored on `branch`, compared with the `live` list. None when they match.

    `stored` is the artifact content when the artifact is Ready, and None otherwise.
    """
    state, data = _read_state(stored, branch, failed=failed)
    if isinstance(state, Notice):
        return state
    if data != json.loads(json.dumps(live)):
        return Notice(STALE, warning=True)
    return None
