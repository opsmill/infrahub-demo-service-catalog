"""The upstream circuits of the cost of service, read apart from the stored query `cost_of_service`.

The circuit schema is optional: `.infrahub.yml` leaves it commented out, and `invoke seed`
loads it with the upstream circuits. The repository import refuses a stored query that names
a type the schema does not have, so the stored query reads no circuit type. The circuits come
from `queries/cost_of_service_circuits.gql`, which `.infrahub.yml` does not register. The cost
transform and the Cost of Service page run it only when the branch's schema has the circuit
endpoint kind, then merge its result into the stored query result with `cost.with_circuits`.

The page and the transform both run it with `read_circuits`. The query file is read relative to this file, so the transform
reads it from its own commit worktree. Both then call `add_footprints`, which asks Infrahub's path
traversal for the devices and, with the circuit query result, the circuits of each active service.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from infrahub_sdk.exceptions import SchemaNotFoundError

from ..business_impact.footprint import service_footprints, with_footprints  # noqa: TID252 - the commit worktree import
from .cost import CIRCUIT_ENDPOINTS, has_circuits

if TYPE_CHECKING:
    from collections.abc import Mapping

    from infrahub_sdk import InfrahubClient

# The circuit endpoint kind, which is also the key of its block in the circuit query result.
CIRCUIT_ENDPOINT_KIND = CIRCUIT_ENDPOINTS
QUERY_FILE = Path(__file__).resolve().parent.parent / "queries" / "cost_of_service_circuits.gql"


def circuit_query() -> str:
    """The text of the circuit query."""
    return QUERY_FILE.read_text(encoding="utf-8")


async def read_circuits(client: InfrahubClient, branch: str) -> dict[str, Any] | None:
    """The circuit query result on `branch`, or None when the branch's schema has no circuit endpoint kind.

    The SDK looks the kind up in its schema cache and reads the branch's schema again only when the kind
    is missing, so a circuit schema that `invoke seed` loads after the repository import is still found.
    """
    try:
        await client.schema.get(kind=CIRCUIT_ENDPOINT_KIND, branch=branch)
    except SchemaNotFoundError:
        return None
    data: dict[str, Any] = await client.execute_graphql(query=circuit_query(), branch_name=branch)
    return data


async def add_footprints(client: InfrahubClient, data: Mapping[str, Any], branch: str) -> dict[str, Any]:
    """The cost data on `branch` with the footprint of each active service on `branch`.

    `data` is the stored query result, merged with the circuit query result when the circuit schema is
    loaded (`cost.with_circuits`). The footprints hold the circuits only then.
    """
    footprints = await service_footprints(client, data, branch, circuits=has_circuits(data))
    return with_footprints(data, footprints)
