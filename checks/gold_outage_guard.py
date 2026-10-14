"""Gold outage guard: fails a proposed change that leaves a service short of its tier's rule or raises an unmet rule.

The check fails when the proposed change leaves an active service with fewer separate paths than its
tier's rule, or raises a tier's rule that the network does not meet.

Registered under `check_definitions`
in `.infrahub.yml` with no `targets`, so it runs once in every proposed change
pipeline. It runs the stored query `business_impact_services` on the proposed
change's branch (the SDK's `collect_data`), reads the same query on main through
`self.client`, and finds the proposed change's name by its source branch. On each
side it adds the footprint of each active service: the core and edge devices that
Infrahub's path traversal (`traverse_paths`) reaches from the service through its
interfaces (`service_catalog.business_impact.footprint`). Then it applies the guard
rule (`service_catalog.business_impact.gold_outage_guard.evaluate`). A traversal
that fails is logged as an error, so the check fails. The two transforms that
reuse the guard run the same module.

How the rule is imported: Infrahub 1.11.4 imports a check file as
`commits.<sha>.checks.gold_outage_guard`, with only the repository directory on
`sys.path` (`infrahub/git/integrator.py`, `execute_python_check`). An absolute
`import service_catalog` therefore fails in the stock Infrahub image, where the
package is not installed. `load_impact` imports the module with `worktree.load`,
the helper the transforms use too, from the same commit worktree as this file.
So the check always runs the rule of the commit it came from. The helper falls
back to the absolute name when this file is imported on its own (unit tests,
`infrahubctl check`). The stored query's name comes from the same module.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any

from infrahub_sdk.checks import InfrahubCheck
from infrahub_sdk.exceptions import Error as SdkError
from infrahub_sdk.protocols import CoreProposedChange

try:
    # Infrahub imports this file as `commits.<sha>.checks.gold_outage_guard`.
    from ..transforms.worktree import IMPACT_MODULE, load  # noqa: TID252 - the commit worktree import
except ImportError:
    # Imported on its own, as `checks.gold_outage_guard`.
    from transforms.worktree import IMPACT_MODULE, load

if TYPE_CHECKING:
    from types import ModuleType


# Infrahub shows a check message in a box that does not wrap lines, about 80 characters wide next to its
# "Message: " label, so the check breaks each message into lines of at most this width.
MESSAGE_WIDTH = 72


def lines(message: str) -> str:
    """The message on lines of at most MESSAGE_WIDTH characters, broken at spaces only, so "DI-2001" stays whole."""
    return textwrap.fill(message, width=MESSAGE_WIDTH, break_long_words=False, break_on_hyphens=False)


def load_impact() -> ModuleType:
    """The module that runs the guard, from this file's commit worktree."""
    module: ModuleType = load(IMPACT_MODULE)
    return module


class GoldOutageGuard(InfrahubCheck):
    query = load_impact().QUERY_NAME
    # Errors of the branch query. `InfrahubCheck.run` hands `validate` only the `data` part of the
    # response when it is not empty, so errors next to partial data are kept here.
    _branch_errors: tuple[str, ...] = ()

    async def collect_data(self) -> dict:
        body: dict[str, Any] = await super().collect_data()
        self._branch_errors = tuple(load_impact().query_errors(body))
        return body

    async def _change_name(self) -> str:
        impact = load_impact()
        changes = await self.client.filters(
            kind=CoreProposedChange,
            source_branch__value=self.branch_name,
            state__value="open",
            branch=impact.MAIN_BRANCH,
        )
        names = sorted(str(change.name.value) for change in changes if change.name.value)
        return names[0] if names else str(impact.FALLBACK_CHANGE_NAME)

    async def validate(self, data: dict) -> None:
        impact = load_impact()
        # A rejected query must fail the check, not read as "no Gold service affected".
        if errors := [*self._branch_errors, *impact.query_errors(data)]:
            self.log_error(message=lines(f"Gold outage guard could not read the proposed change: {'; '.join(errors)}"))
            return
        try:
            main_data, branch_data = await impact.read_main_and_branch(self.client, data, self.branch_name)
        except impact.QueryError as exc:
            self.log_error(
                message=lines(f"Gold outage guard could not read the current network: {'; '.join(exc.messages)}")
            )
            return
        except SdkError as exc:
            self.log_error(message=lines(f"Gold outage guard could not trace the service paths: {exc}"))
            return

        result = impact.evaluate(branch_data, main_data, await self._change_name())
        for message in result.errors:
            self.log_error(message=lines(message))
        for message in result.warnings:
            self.log_info(message=lines(message))
        if result.summary:
            self.log_info(message=lines(result.summary))
