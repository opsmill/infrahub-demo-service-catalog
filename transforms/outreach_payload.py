"""The outreach payload: the Gold customers a new proposed change puts at risk, for the CRM.

Registered under `python_transforms` as `outreach_payload` and used by the
custom webhook `gold-outreach`, which `invoke seed` creates inactive. The
webhook fires on `infrahub.node.created` for `CoreProposedChange`.

Infrahub 1.11.4 calls `transform` with the event, not with the stored query:
`data["data"]` is the event data (`node_id` and the `changelog` of the new
proposed change) and `data["branch"]` is `main`. The `query` below is only
there because `.infrahub.yml` requires one for each Python transform.

The transform reads the source branch and the name of the proposed change
from the changelog, and fetches the proposed change from main by its ID when
the changelog has no source branch. It runs the stored query
`business_impact_services` on the source branch and on main at the same time, with the
footprint of each active service on each (Infrahub's path traversal), runs the Gold
outage guard as the check does, and returns `notification.outreach_payload`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from infrahub_sdk.protocols import CoreProposedChange
from infrahub_sdk.transforms import InfrahubTransform

from .worktree import IMPACT_MODULE, NOTIFICATION_MODULE, load


def _changelog_value(event: dict[str, Any], attribute: str) -> str | None:
    changelog = event.get("changelog") or {}
    value = ((changelog.get("attributes") or {}).get(attribute) or {}).get("value")
    return str(value) if value not in {None, ""} else None


class OutreachPayload(InfrahubTransform):
    query = load(IMPACT_MODULE).QUERY_NAME

    async def _change(self, event: dict[str, Any]) -> tuple[str, str, str]:
        """The proposed change's ID, name and source branch, from the changelog or, failing that, from main."""
        change_id = str(event.get("node_id") or "")
        name = _changelog_value(event, "name")
        source_branch = _changelog_value(event, "source_branch")
        if source_branch is None:
            if not change_id:
                message = "The event names no proposed change: it has no node_id and no source branch"
                raise ValueError(message)
            main_branch = load(IMPACT_MODULE).MAIN_BRANCH
            change = await self.client.get(kind=CoreProposedChange, id=change_id, branch=main_branch)
            source_branch = str(change.source_branch.value)
            name = name or (str(change.name.value) if change.name.value else None)
        return change_id, name or load(IMPACT_MODULE).FALLBACK_CHANGE_NAME, source_branch

    async def transform(self, data: dict) -> dict[str, Any]:
        event = data.get("data") or {}
        change_id, name, source_branch = await self._change(event)
        impact = load(IMPACT_MODULE)
        branch_data, main_data = await asyncio.gather(
            impact.read_branch(self.client, source_branch), impact.read_branch(self.client, impact.MAIN_BRANCH)
        )
        affected, result = impact.affected_on_branch(branch_data, main_data, name)
        payload: dict[str, Any] = load(NOTIFICATION_MODULE).outreach_payload(
            change_id, name, source_branch, affected, result
        )
        return payload
