"""Unit tests for the affected customers list, the outreach payload and the two transforms.

Runs on the seed-shaped query fixture of `builders.py`, with the second path
that `invoke seed` gives each Paris Gold service. The transform tests use the
stand-in client of `builders.py` and an event in the shape Infrahub 1.11.4
sends. The last test imports the transforms the way the Infrahub task worker
does, from a commit worktree.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import re
import shutil
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from infrahub_sdk.node import InfrahubNode
from service_catalog.business_impact.gold_outage_guard import GuardResult, evaluate
from service_catalog.business_impact.notification import (
    STATUS_AT_RISK_CHANGE_BLOCKED,
    STATUS_AT_RISK_NOT_NOTIFIED,
    STATUS_AT_RISK_NOTIFIED,
    STATUS_DOWN_CHANGE_BLOCKED,
    STATUS_DOWN_NOT_NOTIFIED,
    AffectedCustomer,
    affected_customers,
    affected_customers_report,
    outreach_payload,
)
from service_catalog.network import QueryError
from tests.unit.builders import (
    BRUSSELS,
    NEW_YORK,
    PARIS,
    PARIS_SECOND_PATHS,
    REPO_ROOT,
    SEED,
    QueryClient,
    build_q1,
    build_seeded_q1,
    proposed_change,
)
from transforms.affected_customers import AffectedCustomers
from transforms.outreach_payload import OutreachPayload

if TYPE_CHECKING:
    from pathlib import Path

    from infrahub_sdk import InfrahubClient

CONTACT_WORDS = re.compile(r"@|e-?mail|phone|address|contact", re.IGNORECASE)


MAIN = build_seeded_q1()
CHANGES = {
    PARIS: ("maint-rb01-par01", build_seeded_q1({"rb01-par01": "maintenance"})),
    BRUSSELS: ("maint-sw01-bru01", build_seeded_q1({"sw01-bru01": "maintenance"})),
    NEW_YORK: ("maint-rb01-nyc01", build_seeded_q1({"rb01-nyc01": "maintenance"})),
}


def _affected(name: str) -> tuple[list[AffectedCustomer], GuardResult]:
    _, branch = CHANGES[name]
    result = evaluate(branch, MAIN, name)
    return affected_customers(branch, MAIN, result), result


def _rows(affected: list[AffectedCustomer]) -> list[tuple[str, str, tuple[str, ...], str]]:
    return [(row.customer, row.tier, row.services, row.status) for row in affected]


# The affected customers list


def test_paris_lists_four_customers_with_two_gold_at_risk() -> None:
    affected, result = _affected(PARIS)

    assert result.passed
    assert _rows(affected) == [
        ("Helix Health", "Gold", ("DI-1003",), STATUS_AT_RISK_NOTIFIED),
        ("Northbank", "Gold", ("DI-1001", "DI-1002"), STATUS_AT_RISK_NOTIFIED),
        ("Maison Verte", "Silver", ("DI-1004",), STATUS_DOWN_NOT_NOTIFIED),
        ("Rapid Freight", "Bronze", ("DI-1006",), STATUS_DOWN_NOT_NOTIFIED),
    ]


def test_paris_report_matches_the_artifact_contract() -> None:
    affected, result = _affected(PARIS)

    assert affected_customers_report("maint-rb01-par01", affected, result) == {
        "branch": "maint-rb01-par01",
        "blocked": False,
        "customers": [
            {"customer": "Helix Health", "tier": "Gold", "services": ["DI-1003"], "status": "at risk, notified"},
            {
                "customer": "Northbank",
                "tier": "Gold",
                "services": ["DI-1001", "DI-1002"],
                "status": "at risk, notified",
            },
            {"customer": "Maison Verte", "tier": "Silver", "services": ["DI-1004"], "status": "down, not notified"},
            {"customer": "Rapid Freight", "tier": "Bronze", "services": ["DI-1006"], "status": "down, not notified"},
        ],
    }


def test_brussels_is_blocked_and_its_gold_service_is_down_change_blocked() -> None:
    affected, result = _affected(BRUSSELS)

    assert not result.passed
    assert _rows(affected) == [
        ("Helix Health", "Gold", ("DI-2001",), STATUS_DOWN_CHANGE_BLOCKED),
        ("Maison Verte", "Silver", ("DI-2003",), STATUS_DOWN_NOT_NOTIFIED),
        ("Rapid Freight", "Bronze", ("DI-2005",), STATUS_DOWN_NOT_NOTIFIED),
    ]
    assert affected_customers_report("maint-sw01-bru01", affected, result)["blocked"] is True


def test_new_york_affects_no_customer() -> None:
    affected, result = _affected(NEW_YORK)

    assert result.passed
    assert affected == []


def test_main_affects_no_customer() -> None:
    result = evaluate(MAIN, MAIN, "Current network")

    assert affected_customers(MAIN, MAIN, result) == []


def test_silver_and_bronze_only_change_lists_them_and_notifies_no_one() -> None:
    """Acceptance 2.5: no Gold service affected, an empty outreach list, the artifact still lists the others."""
    rows = tuple(replace(row, tier="Silver") if row.tier == "Gold" else row for row in SEED)
    branch = build_q1({"rb01-par01": "maintenance"}, rows=rows)
    main = build_q1(rows=rows)
    result = evaluate(branch, main, PARIS)

    affected = affected_customers(branch, main, result)

    assert result.passed
    assert _rows(affected) == [
        ("Maison Verte", "Silver", ("DI-1004",), STATUS_DOWN_NOT_NOTIFIED),
        ("Northbank", "Silver", ("DI-1001", "DI-1002"), STATUS_DOWN_NOT_NOTIFIED),
        ("Rapid Freight", "Bronze", ("DI-1006",), STATUS_DOWN_NOT_NOTIFIED),
    ]
    payload = outreach_payload("pc-1", PARIS, "maint-rb01-par01", affected, result)
    assert payload["blocked"] is False
    assert payload["customers"] == []


def test_one_row_per_customer_and_tier() -> None:
    """A customer with Gold and Silver services affected has one row per tier."""
    rows = tuple(replace(row, customer="Northbank") if row.identifier == "DI-1004" else row for row in SEED)
    branch = build_q1({"rb01-par01": "maintenance"}, rows=rows, second_paths=PARIS_SECOND_PATHS)
    main = build_q1(rows=rows, second_paths=PARIS_SECOND_PATHS)

    affected = affected_customers(branch, main, evaluate(branch, main, PARIS))

    assert [(row.customer, row.tier) for row in affected] == [
        ("Helix Health", "Gold"),
        ("Northbank", "Gold"),
        ("Northbank", "Silver"),
        ("Rapid Freight", "Bronze"),
    ]


def test_gold_service_with_a_path_left_in_a_blocked_change_is_not_notified() -> None:
    """Paris and Brussels in one change: the guard blocks it, so the Paris Gold services are not notified."""
    branch = build_seeded_q1({"rb01-par01": "maintenance", "sw01-bru01": "maintenance"})
    result = evaluate(branch, MAIN, "Two sites")

    affected = affected_customers(branch, MAIN, result)

    gold = {row.customer: (row.services, row.status) for row in affected if row.tier == "Gold"}
    assert gold == {
        "Helix Health": (("DI-1003", "DI-2001"), STATUS_DOWN_CHANGE_BLOCKED),
        "Northbank": (("DI-1001", "DI-1002"), STATUS_AT_RISK_CHANGE_BLOCKED),
    }
    assert all(row.notified_services == () for row in affected)


def test_silver_service_with_a_path_left_is_at_risk_and_not_notified() -> None:
    """DI-1004 gets a second path, so the Paris router 1 maintenance leaves it one."""
    second_paths = {**PARIS_SECOND_PATHS, "DI-1004": ("sw02-par01", "rb02-par01")}
    branch = build_q1({"rb01-par01": "maintenance"}, second_paths=second_paths)
    main = build_q1(second_paths=second_paths)

    affected = affected_customers(branch, main, evaluate(branch, main, PARIS))

    silver = [(row.customer, row.services, row.status) for row in affected if row.tier == "Silver"]
    assert silver == [("Maison Verte", ("DI-1004",), STATUS_AT_RISK_NOT_NOTIFIED)]


# The outreach payload


def test_paris_payload_lists_northbank_and_helix_health() -> None:
    affected, result = _affected(PARIS)

    assert outreach_payload("pc-paris", PARIS, "maint-rb01-par01", affected, result) == {
        "source": "infrahub",
        "proposed_change": {"id": "pc-paris", "name": PARIS, "source_branch": "maint-rb01-par01"},
        "blocked": False,
        "customers": [
            {"customer": "Helix Health", "tier": "Gold", "services": ["DI-1003"]},
            {"customer": "Northbank", "tier": "Gold", "services": ["DI-1001", "DI-1002"]},
        ],
    }


@pytest.mark.parametrize(
    ("change_id", "name", "branch", "blocked"),
    [
        ("pc-brussels", BRUSSELS, "maint-sw01-bru01", True),
        ("pc-nyc", NEW_YORK, "maint-rb01-nyc01", False),
    ],
    ids=["brussels-blocked", "new-york-empty"],
)
def test_payload_with_no_customer(change_id: str, name: str, branch: str, *, blocked: bool) -> None:
    affected, result = _affected(name)

    payload = outreach_payload(change_id, name, branch, affected, result)

    assert payload["blocked"] is blocked
    assert payload["customers"] == []


def test_payload_never_lists_silver_or_bronze() -> None:
    affected, result = _affected(PARIS)

    payload = outreach_payload("pc-paris", PARIS, "maint-rb01-par01", affected, result)

    assert {customer["tier"] for customer in payload["customers"]} == {"Gold"}


@pytest.mark.parametrize("name", [PARIS, BRUSSELS, NEW_YORK])
def test_no_contact_details_in_any_output(name: str) -> None:
    """Acceptance 2.6: customer names and tiers, no email address, phone number or contact field."""
    branch_name, _ = CHANGES[name]
    affected, result = _affected(name)
    outputs = (
        affected_customers_report(branch_name, affected, result),
        outreach_payload("pc", name, branch_name, affected, result),
    )

    for output in outputs:
        assert not CONTACT_WORDS.search(json.dumps(output))
    assert {key for row in outputs[0]["customers"] for key in row} <= {"customer", "tier", "services", "status"}
    assert {key for row in outputs[1]["customers"] for key in row} <= {"customer", "tier", "services"}


# The transforms, with a stand-in client


class _TransformClient(QueryClient):
    """The stand-in client of the check tests, plus what a transform needs.

    A transform clones its client for its branch, and the outreach transform fetches the proposed change by
    ID when the changelog has no source branch.
    """

    def __init__(self, data_by_branch: dict[str, dict[str, Any]], change: tuple[str, str] | None = None) -> None:
        super().__init__(data_by_branch, None)
        self.change = change
        self.fetched: list[dict[str, object]] = []

    def clone(self, **_: object) -> _TransformClient:
        return self

    async def get(self, **kwargs: object) -> object:
        assert self.change is not None
        self.fetched.append(kwargs)
        return proposed_change(*self.change)


def _client(change: tuple[str, str] | None = None) -> _TransformClient:
    return _TransformClient(dict(CHANGES.values()) | {"main": MAIN}, change)


def _event(name: str | None, source_branch: str | None) -> dict[str, Any]:
    """The `data` that Infrahub 1.11.4 passes to a webhook transform for a new proposed change."""
    attributes: dict[str, Any] = {
        "state": {"kind": "Text", "name": "state", "value": "open"},
        "destination_branch": {"kind": "Text", "name": "destination_branch", "value": "main"},
    }
    if name is not None:
        attributes["name"] = {"kind": "Text", "name": "name", "value": name}
    if source_branch is not None:
        attributes["source_branch"] = {"kind": "Text", "name": "source_branch", "value": source_branch}
    return {
        "data": {
            "data": {
                "kind": "CoreProposedChange",
                "action": "created",
                "node_id": "pc-1",
                "changelog": {"node_id": "pc-1", "node_kind": "CoreProposedChange", "attributes": attributes},
            },
            "id": "event-1",
            "branch": "main",
            "event": "infrahub.node.created",
        }
    }


def _outreach(client: QueryClient, event: dict[str, Any]) -> dict[str, Any]:
    transform = OutreachPayload(client=cast("InfrahubClient", client), infrahub_node=InfrahubNode, branch="main")
    return cast("dict[str, Any]", asyncio.run(transform.run(data=event)))


def test_outreach_transform_reads_the_change_from_the_changelog() -> None:
    client = _client()

    payload = _outreach(client, _event(PARIS, "maint-rb01-par01"))

    assert payload["proposed_change"] == {"id": "pc-1", "name": PARIS, "source_branch": "maint-rb01-par01"}
    assert [customer["customer"] for customer in payload["customers"]] == ["Helix Health", "Northbank"]
    assert set(client.reads) == {("business_impact_services", "maint-rb01-par01"), ("business_impact_services", "main")}


def test_outreach_transform_is_blocked_on_brussels() -> None:
    payload = _outreach(_client(), _event(BRUSSELS, "maint-sw01-bru01"))

    assert payload["blocked"] is True
    assert payload["customers"] == []


def test_outreach_transform_fetches_the_change_when_the_changelog_has_no_source_branch() -> None:
    client = _client((NEW_YORK, "maint-rb01-nyc01"))

    payload = _outreach(client, _event(None, None))

    assert client.fetched == [{"kind": client.fetched[0]["kind"], "id": "pc-1", "branch": "main"}]
    assert payload["proposed_change"] == {"id": "pc-1", "name": NEW_YORK, "source_branch": "maint-rb01-nyc01"}
    assert payload["customers"] == []


def test_outreach_transform_refuses_an_event_with_no_node_id_and_no_source_branch() -> None:
    client = _client((NEW_YORK, "maint-rb01-nyc01"))
    event = _event(PARIS, None)
    del event["data"]["data"]["node_id"]

    with pytest.raises(ValueError, match="no node_id and no source branch"):
        _outreach(client, event)
    assert client.fetched == []
    assert client.reads == []


def _affected_artifact(client: QueryClient, branch: str) -> dict[str, Any]:
    transform = AffectedCustomers(client=cast("InfrahubClient", client), infrahub_node=InfrahubNode, branch=branch)
    return cast("dict[str, Any]", asyncio.run(transform.run()))


def test_affected_customers_transform_on_the_paris_branch() -> None:
    client = _client()

    artifact = _affected_artifact(client, "maint-rb01-par01")

    assert artifact["branch"] == "maint-rb01-par01"
    assert artifact["blocked"] is False
    assert [(row["customer"], row["status"]) for row in artifact["customers"]] == [
        ("Helix Health", "at risk, notified"),
        ("Northbank", "at risk, notified"),
        ("Maison Verte", "down, not notified"),
        ("Rapid Freight", "down, not notified"),
    ]


def test_affected_customers_transform_on_main_lists_no_customer() -> None:
    assert _affected_artifact(_client(), "main") == {"branch": "main", "blocked": False, "customers": []}


def test_affected_customers_transform_fails_when_the_query_returns_errors() -> None:
    """A rejected query must fail the artifact, not read as "no customer affected"."""
    client = _TransformClient({"maint-rb01-par01": {"data": MAIN, "errors": [{"message": "denied"}]}, "main": MAIN})

    with pytest.raises(QueryError, match="denied"):
        _affected_artifact(client, "maint-rb01-par01")


def test_worker_imports_the_rules_from_the_commit_worktree(commit_worktree: Path) -> None:
    """Infrahub 1.11.4 imports `commits.<sha>.transforms.<name>` with only the repository directory on sys.path,
    so each transform must reach `service_catalog` inside the same worktree, not an installed copy.
    """
    worktree = commit_worktree
    package = f"commits.{worktree.name}"
    shutil.copytree(REPO_ROOT / "transforms", worktree / "transforms", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(
        REPO_ROOT / "service_catalog" / "business_impact",
        worktree / "service_catalog" / "business_impact",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for name in ("network.py", "protocols_async.py"):
        shutil.copy(REPO_ROOT / "service_catalog" / name, worktree / "service_catalog" / name)
    for name in ("affected_customers", "outreach_payload"):
        importlib.import_module(f"{package}.transforms.{name}")
    shared = importlib.import_module(f"{package}.transforms.worktree")
    for module in (shared.IMPACT_MODULE, shared.NOTIFICATION_MODULE, shared.NETWORK_MODULE):
        loaded = shared.load(module)
        assert loaded.__name__ == f"{package}.{module}"
        assert loaded.__file__.startswith(str(worktree))
    client = _client()
    transform = importlib.import_module(f"{package}.transforms.outreach_payload").OutreachPayload(
        client=cast("InfrahubClient", client), infrahub_node=InfrahubNode, branch="main"
    )
    payload = asyncio.run(transform.run(data=_event(PARIS, "maint-rb01-par01")))
    assert [customer["customer"] for customer in payload["customers"]] == ["Helix Health", "Northbank"]
