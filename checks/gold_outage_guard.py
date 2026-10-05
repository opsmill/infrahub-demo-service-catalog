"""Gold outage guard: a proposed change that takes an active Gold service out of service cannot merge.

Registered under `check_definitions`
in `.infrahub.yml` with no `targets`, so it runs once in every proposed change
pipeline. It runs the stored query `business_impact_services` on the proposed
change's branch (the SDK's `collect_data`), reads the same query on main through
`self.client`, finds the proposed change's name by its source branch, and hands
both results to `service_catalog.business_impact.gold_outage_guard.evaluate`.

How the rule is imported: Infrahub 1.11.4 imports a check file as
`commits.<sha>.checks.gold_outage_guard`, with only the repository directory on
`sys.path` (`infrahub/git/integrator.py`, `execute_python_check`). An absolute
`import service_catalog` therefore fails in the stock Infrahub image, where the
package is not installed. `load_rule` imports the rule from the same commit
worktree as this file, so the check always runs the rule of the commit it came
from, and falls back to the absolute name when this file is imported on its own
(unit tests, `infrahubctl check`).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from infrahub_sdk.checks import InfrahubCheck
from infrahub_sdk.protocols import CoreProposedChange

if TYPE_CHECKING:
    from types import ModuleType

QUERY_NAME = "business_impact_services"
MAIN_BRANCH = "main"
RULE_MODULE = "service_catalog.business_impact.gold_outage_guard"
FALLBACK_CHANGE_NAME = "This change"


def load_rule() -> ModuleType:
    """Import the rule module from this file's commit worktree, or by its absolute name."""
    worktree_package = (__package__ or "").rpartition(".")[0]
    name = f"{worktree_package}.{RULE_MODULE}" if worktree_package else RULE_MODULE
    return importlib.import_module(name)


def _query_errors(body: dict[str, Any]) -> list[str]:
    errors = body.get("errors") or []
    return [str(error.get("message", error)) if isinstance(error, dict) else str(error) for error in errors]


class GoldOutageGuard(InfrahubCheck):
    query = QUERY_NAME
    # Errors of the branch query. `InfrahubCheck.run` hands `validate` only the `data` part of the
    # response when it is not empty, so errors next to partial data are kept here.
    _branch_errors: tuple[str, ...] = ()

    async def collect_data(self) -> dict:
        body: dict[str, Any] = await super().collect_data()
        self._branch_errors = tuple(_query_errors(body))
        return body

    async def _change_name(self) -> str:
        changes = await self.client.filters(
            kind=CoreProposedChange, source_branch__value=self.branch_name, state__value="open", branch=MAIN_BRANCH
        )
        names = sorted(str(change.name.value) for change in changes if change.name.value)
        return names[0] if names else FALLBACK_CHANGE_NAME

    async def validate(self, data: dict) -> None:
        # A rejected query must fail the check, not read as "no Gold service affected".
        if errors := [*self._branch_errors, *_query_errors(data)]:
            self.log_error(message=f"Gold outage guard could not read the proposed change: {'; '.join(errors)}")
            return
        main_body = await self.client.query_gql_query(name=QUERY_NAME, branch_name=MAIN_BRANCH, update_group=False)
        if errors := _query_errors(main_body):
            self.log_error(message=f"Gold outage guard could not read the current network: {'; '.join(errors)}")
            return

        result = load_rule().evaluate(data, main_body.get("data") or {}, await self._change_name())
        for message in result.errors:
            self.log_error(message=message)
        for message in result.warnings:
            self.log_info(message=message)
