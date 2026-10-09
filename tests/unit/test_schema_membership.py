"""Pin the set of kinds that implement `OrganizationGeneric`.

A generic's implementer set is a published interface: adding a kind passes
`infrahubctl schema check` and creates no migration, yet it changes what every
query, relationship peer and consumer over the generic returns. For example,
`LocationSite.owner`, `LocationRack.owner` and `IpamPrefix.organization`
peer `OrganizationGeneric`, so a new implementer becomes a legal peer there.
The module also pins the kind, optionality and branch setting of the tier
rule (`ServiceTier.min_paths`) and the request record (`ServiceGeneric`
`requested_by` and `request_reason`). These tests read the schema YAML off
disk, so they need no server.
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


def _attributes(path: Path, section: str, kind: str) -> dict[str, dict[str, Any]]:
    """Return the attributes of one generic or node in a schema file, by attribute name."""
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for entry in document.get(section) or []:
        if f"{entry['namespace']}{entry['name']}" == kind:
            return {attribute["name"]: attribute for attribute in entry.get("attributes") or []}
    raise AssertionError(f"{kind} is not declared under {section} in {path.name}")


def test_tier_rule_and_request_record_attributes() -> None:
    """The tier rule is an optional number; the request record is optional text kept the same on every branch."""
    tier = _attributes(SCHEMA_DIR / "service" / "tier.yml", "nodes", "ServiceTier")
    assert tier["min_paths"]["kind"] == "Number"
    assert tier["min_paths"]["optional"] is True
    assert "branch" not in tier["min_paths"]

    service = _attributes(SCHEMA_DIR / "service" / "service.yml", "generics", "ServiceGeneric")
    for name in ("requested_by", "request_reason"):
        assert service[name]["kind"] == "Text"
        assert service[name]["optional"] is True
        assert service[name]["branch"] == "agnostic"
