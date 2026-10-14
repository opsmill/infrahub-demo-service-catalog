"""The "Cost of service" artifact: one CSV row per service, path and part.

Registered under `python_transforms` as `cost_of_service` and used by the
artifact definition "Cost of service", which targets the `ServiceReport`
object of the same name. Infrahub runs the stored query `cost_of_service` and
hands its result to `transform`. When the branch's schema has the circuit
schema, `transform` also runs the circuit query (`circuits.read_circuits`) and
merges its result with `cost.with_circuits`. Then it adds the footprint of each
active service, the devices and circuits Infrahub's path traversal reaches from
it (`circuits.add_footprints`). It returns the CSV of `cost.cost_lines` for that data. The Cost of Service page computes its
figures with the same functions from the same two queries.

Infrahub generates the artifact again only when a node of the stored query
result changes. A change to a circuit, such as its monthly cost, does not
regenerate it. The Cost of Service page compares the stored CSV with the CSV of
its own figures, says when the stored file is older, and offers to generate it
again.

The cost module is imported from this file's commit worktree, as
`worktree.load` explains.
"""

from __future__ import annotations

from typing import Any

from infrahub_sdk.transforms import InfrahubTransform

from .worktree import NETWORK_MODULE, load

COST_MODULE = "service_catalog.cost_of_service.cost"
CIRCUITS_MODULE = "service_catalog.cost_of_service.circuits"


class CostOfService(InfrahubTransform):
    query = "cost_of_service"

    async def collect_data(self) -> dict:
        # Errors next to partial data must stop the artifact instead of reading as a service with no cost.
        body: dict[str, Any] = await super().collect_data()
        load(NETWORK_MODULE).query_data(body, f"branch {self.branch_name}")
        return body

    async def transform(self, data: dict) -> str:
        cost = load(COST_MODULE)
        circuits = load(CIRCUITS_MODULE)
        merged = cost.with_circuits(data, await circuits.read_circuits(self.client, self.branch_name))
        traced = await circuits.add_footprints(self.client, merged, self.branch_name)
        content: str = cost.to_csv(cost.cost_lines(traced))
        return content
