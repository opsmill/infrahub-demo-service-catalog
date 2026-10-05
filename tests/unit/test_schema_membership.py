"""Pin the set of kinds that implement `OrganizationGeneric`.

A generic's implementer set is a published interface: adding a kind passes
`infrahubctl schema check` and creates no migration, yet it changes what every
query, relationship peer and consumer over the generic returns. For example,
`LocationSite.owner`, `LocationRack.owner` and `IpamPrefix.organization`
peer `OrganizationGeneric`, so a new implementer becomes a legal peer there.
This test reads the schema YAML off disk, so it needs no server.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"

GENERIC = "OrganizationGeneric"

EXPECTED_ORGANIZATION_IMPLEMENTERS = {
    "OrganizationManufacturer",
    "OrganizationProvider",
    "OrganizationCustomer",
    # Adding a kind here is a deliberate act: check every query, peer and
    # consumer over OrganizationGeneric first.
}


def _declared_nodes() -> Iterator[dict[str, Any]]:
    """Yield every node declared across the repository's schema files."""
    paths = sorted([*SCHEMA_DIR.rglob("*.yml"), *SCHEMA_DIR.rglob("*.yaml")])
    for path in paths:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        yield from document.get("nodes") or []


def test_organization_generic_implementers_are_pinned() -> None:
    actual = {
        f"{node['namespace']}{node['name']}"
        for node in _declared_nodes()
        if GENERIC in (node.get("inherit_from") or [])
    }
    added = actual - EXPECTED_ORGANIZATION_IMPLEMENTERS
    removed = EXPECTED_ORGANIZATION_IMPLEMENTERS - actual
    message = (
        f"{GENERIC} implementer set changed. Added: {sorted(added)}. Removed: {sorted(removed)}. "
        f"Every query, relationship peer and consumer over {GENERIC} now answers differently. "
        "Change EXPECTED_ORGANIZATION_IMPLEMENTERS only after checking them."
    )
    assert not added, message
    assert not removed, message
