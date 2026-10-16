"""The "Affected customers" artifact: each customer a proposed change affects, with its tier and status.

Registered under `python_transforms` as `affected_customers` and used by the
artifact definition "Affected customers", which targets the `ServiceReport`
object of the same name. Infrahub generates the artifact on each branch, so a
proposed change has its own list on its source branch. On main it lists no
customer.

Infrahub runs the stored query `business_impact_services` on the branch and
hands its result to `transform`. The transform reads the same query on main
through `self.client`, adds the footprint of each active service on the branch
and on main (Infrahub's path traversal), runs the Gold outage guard as the check
does, and returns `change_impact.affected_report`.

Infrahub generates the artifact again when a node of the branch's query result
changes, and in each proposed change pipeline. A change merged into main, or a
change to the links between interfaces, does not regenerate it. The Customer
notification page computes the same content from the live data with
`change_impact.read_affected_report`, says when the stored artifact is older,
and offers to generate it again.
"""

from __future__ import annotations

from typing import Any

from infrahub_sdk.transforms import InfrahubTransform

from .worktree import IMPACT_MODULE, NETWORK_MODULE, load


class AffectedCustomers(InfrahubTransform):
    query = load(IMPACT_MODULE).QUERY_NAME

    async def collect_data(self) -> dict:
        # `InfrahubTransform.run` hands `transform` only the `data` part, so errors next to partial data
        # must stop the artifact here instead of reading as "no customer affected".
        body: dict[str, Any] = await super().collect_data()
        load(NETWORK_MODULE).query_data(body, f"branch {self.branch_name}")
        return body

    async def transform(self, data: dict) -> dict[str, Any]:
        impact = load(IMPACT_MODULE)
        main_data, branch_data = await impact.read_main_and_branch(self.client, data, self.branch_name)
        report: dict[str, Any] = impact.affected_report(self.branch_name, branch_data, main_data)
        return report
