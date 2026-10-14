"""The worktree import the transforms and the Gold outage guard check share.

Infrahub 1.11.4 imports a Python transform file as
`commits.<sha>.transforms.<name>`, with only the repository directory on
`sys.path`, as it does for a check. An absolute `import service_catalog` fails
in the stock Infrahub image. `load` imports a module from the same commit
worktree as this file, and falls back to the absolute name when this file is
imported on its own (unit tests, `infrahubctl transform`).

The check (`checks/gold_outage_guard.py`), the affected customers transform and
the outreach transform run the Gold outage guard through
`service_catalog.business_impact.change_impact`, and take the name of their
stored query, `QUERY_NAME`, from it. Every transform reads its stored query result
through `service_catalog.network.query_data`.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

IMPACT_MODULE = "service_catalog.business_impact.change_impact"
NOTIFICATION_MODULE = "service_catalog.business_impact.notification"
NETWORK_MODULE = "service_catalog.network"


def load(module: str) -> ModuleType:
    """Import `module` from this file's commit worktree, or by its absolute name."""
    worktree_package = (__package__ or "").rpartition(".")[0]
    name = f"{worktree_package}.{module}" if worktree_package else module
    return importlib.import_module(name)
