"""The Gold outage guard run on a proposed change, as the check and the transforms run it.

`checks/gold_outage_guard.py`, `transforms/affected_customers.py` and
`transforms/outreach_payload.py` read the stored query `business_impact_services`
on the change's branch and on main with `read_branch`, which adds the footprint
of each active service (`footprint.service_footprints`), then apply the guard
rule (`gold_outage_guard.evaluate`). The transforms hand the result to
`notification`.

The imports are relative on purpose: the Infrahub task worker imports this
module from the commit worktree as `commits.<sha>.service_catalog...`, where an
absolute `service_catalog` import does not resolve. The check and the
transforms load it with their own worktree-relative import.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..network import QueryError, query_data, query_errors  # noqa: TID252 - the commit worktree import
from .blast_radius import MAIN_BRANCH
from .footprint import service_footprints, with_footprints
from .gold_outage_guard import evaluate
from .notification import affected_customers, affected_customers_report

if TYPE_CHECKING:
    from collections.abc import Mapping

    from infrahub_sdk import InfrahubClient

    from .gold_outage_guard import GuardResult
    from .notification import AffectedCustomer

QUERY_NAME = "business_impact_services"
FALLBACK_CHANGE_NAME = "This change"

# `MAIN_BRANCH`, `QueryError` and `query_errors` are read through this module by the check and the transforms.
__all__ = [
    "FALLBACK_CHANGE_NAME",
    "MAIN_BRANCH",
    "QUERY_NAME",
    "QueryError",
    "add_footprints",
    "affected_on_branch",
    "affected_report",
    "evaluate",
    "query_errors",
    "read_affected_report",
    "read_branch",
    "read_main_and_branch",
]


async def read_branch(client: InfrahubClient, branch: str) -> dict[str, Any]:
    """The stored query on `branch`, without adding the query to a group, with the footprints on `branch`."""
    body = await client.query_gql_query(name=QUERY_NAME, branch_name=branch, update_group=False)
    return await add_footprints(client, query_data(body, f"branch {branch}"), branch)


async def add_footprints(client: InfrahubClient, data: Mapping[str, Any], branch: str) -> dict[str, Any]:
    """The query result on `branch` with the footprint of each active service on `branch`."""
    return with_footprints(data, await service_footprints(client, data, branch))


async def read_main_and_branch(
    client: InfrahubClient, branch_data: Mapping[str, Any], branch: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The stored query on main and `branch_data` on `branch`, each with its footprints, as (main, branch).

    The two sides do not depend on each other, so their traversals run at the same time.
    """
    main_data, with_branch_footprints = await asyncio.gather(
        read_branch(client, MAIN_BRANCH), add_footprints(client, branch_data, branch)
    )
    return main_data, with_branch_footprints


def affected_on_branch(
    branch_data: Mapping[str, object],
    main_data: Mapping[str, object],
    change_name: str = FALLBACK_CHANGE_NAME,
) -> tuple[list[AffectedCustomer], GuardResult]:
    """The affected customers of a change and the guard's result, as the check computes it."""
    result = evaluate(branch_data, main_data, change_name)
    return affected_customers(branch_data, main_data, result), result


def affected_report(branch: str, branch_data: Mapping[str, object], main_data: Mapping[str, object]) -> dict[str, Any]:
    """The content of the "Affected customers" artifact for the change on `branch`."""
    affected, result = affected_on_branch(branch_data, main_data)
    return affected_customers_report(branch, affected, result)


async def read_affected_report(client: InfrahubClient, branch: str) -> dict[str, Any]:
    """The "Affected customers" content for `branch`, from the stored query and the footprints read now on
    `branch` and on main.

    The Customer notification page compares it with the artifact Infrahub stored, which can be older.
    """
    branch_data, main_data = await asyncio.gather(read_branch(client, branch), read_branch(client, MAIN_BRANCH))
    return affected_report(branch, branch_data, main_data)
