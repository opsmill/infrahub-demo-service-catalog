"""Unit tests for the Gold outage guard rule.

Runs `evaluate` on the seed-shaped query fixture of `test_blast_radius.py`: the
same twelve services and sixteen devices, with every device active unless a
test sets its status. The last tests import the check file the way the
Infrahub task worker does, from a commit worktree, to prove that the check
reaches the rule in that worktree and needs no installed `service_catalog`.
"""

from __future__ import annotations

import asyncio
import importlib
import shutil
import sys
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from checks.gold_outage_guard import GoldOutageGuard
from infrahub_sdk.exceptions import GraphQLError
from service_catalog.business_impact.blast_radius import DeviceRow, parse_devices
from service_catalog.business_impact.gold_outage_guard import (
    MAX_HOPS,
    NETWORK_KINDS,
    GuardResult,
    evaluate,
    move_to_device,
    traversal_pairs,
)
from tests.unit.test_blast_radius import FORBIDDEN_COPY, REPO_ROOT, SEED, build_q1

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    from infrahub_sdk import InfrahubClient

PARIS = "Paris router 1 maintenance"
BRUSSELS = "Brussels switch 1 maintenance"
NEW_YORK = "New York router 1 maintenance"

PARIS_MESSAGE = (
    "Paris router 1 maintenance leaves 2 Gold services for Northbank with no other path (DI-1001, DI-1002). "
    "Gold SLA credit exposure: €2,565 per month (demo business input). "
    "Move these services to Paris edge router 2 first."
)
BRUSSELS_MESSAGE = (
    "Brussels switch 1 maintenance leaves 1 Gold service for Helix Health with no other path (DI-2001). "
    "Gold SLA credit exposure: €2,025 per month (demo business input). "
    "Move this service to Brussels switch 2 first."
)


def _passed_clean(result: GuardResult) -> bool:
    return result.passed and not result.errors and not result.warnings


def test_paris_router_1_maintenance_fails_with_the_documented_message() -> None:
    result = evaluate(build_q1({"rb01-par01": "maintenance"}), build_q1(), PARIS)

    assert not result.passed
    assert result.errors == [PARIS_MESSAGE]
    assert result.warnings == []


def test_brussels_switch_1_maintenance_fails_with_the_singular_message() -> None:
    result = evaluate(build_q1({"sw01-bru01": "maintenance"}), build_q1(), BRUSSELS)

    assert result.errors == [BRUSSELS_MESSAGE]
    assert result.warnings == []


def test_new_york_router_1_maintenance_passes() -> None:
    """No active service runs through `rb01-nyc01`."""
    result = evaluate(build_q1({"rb01-nyc01": "maintenance"}), build_q1(), NEW_YORK)

    assert _passed_clean(result)


def test_main_passes() -> None:
    """A change that sets no device status, such as a service order."""
    main = build_q1()

    assert _passed_clean(evaluate(main, main, "Implement service DI-3001"))


def test_silver_or_bronze_only_passes() -> None:
    """No Gold service behind the device."""
    rows = tuple(replace(row, tier="Silver") if row.tier == "Gold" else row for row in SEED)

    result = evaluate(build_q1({"rb01-par01": "maintenance"}, rows=rows), build_q1(rows=rows), PARIS)

    assert _passed_clean(result)


def test_unassigned_tier_passes() -> None:
    rows = tuple(replace(row, tier=None) if row.tier == "Gold" else row for row in SEED)

    result = evaluate(build_q1({"rb01-par01": "maintenance"}, rows=rows), build_q1(rows=rows), PARIS)

    assert _passed_clean(result)


def test_gold_device_already_out_of_service_on_main_passes_with_one_warning() -> None:
    """An existing problem does not block an unrelated change."""
    main = build_q1({"sw01-bru01": "maintenance"})
    branch = build_q1({"sw01-bru01": "maintenance", "rb01-nyc01": "maintenance"})

    result = evaluate(branch, main, NEW_YORK)

    assert result.passed
    assert result.errors == []
    assert len(result.warnings) == 1
    assert "DI-2001" in result.warnings[0]
    assert "Helix Health" in result.warnings[0]


def test_already_out_device_with_another_status_still_only_warns() -> None:
    """Moving a device from one out-of-service status to another does not take a service out of service."""
    main = build_q1({"sw01-bru01": "provisioning"})
    branch = build_q1({"sw01-bru01": "maintenance"})

    result = evaluate(branch, main, BRUSSELS)

    assert result.errors == []
    assert [warning for warning in result.warnings if "DI-2001" in warning] == result.warnings
    assert len(result.warnings) == 1


def test_inactive_gold_service_is_ignored() -> None:
    rows = tuple(replace(row, status="draft") if row.identifier == "DI-2001" else row for row in SEED)

    result = evaluate(build_q1({"sw01-bru01": "maintenance"}, rows=rows), build_q1(rows=rows), BRUSSELS)

    assert _passed_clean(result)


def test_two_customers_joined_with_and_in_name_order() -> None:
    """Paris switch 1 and Brussels switch 1 together: Northbank and Helix Health, in name order."""
    branch = build_q1({"rb01-par01": "maintenance", "sw01-bru01": "maintenance"})

    result = evaluate(branch, build_q1(), "Two sites")

    assert result.errors == [
        "Two sites leaves 3 Gold services for Helix Health and Northbank with no other path (DI-1001, DI-1002, DI-2001). "
        "Gold SLA credit exposure: €4,590 per month (demo business input). "
        "Move these services to Brussels switch 2 and Paris edge router 2 first."
    ]


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        ("rb01-par01", "Paris edge router 2"),
        ("rb02-par01", "Paris edge router 1"),
        ("sw01-bru01", "Brussels switch 2"),
        ("sw02-bru01", "Brussels switch 1"),
    ],
)
def test_move_to_device_is_same_role_other_index_same_site_by_description(device: str, expected: str) -> None:
    devices = parse_devices(build_q1())
    target = move_to_device(next(row for row in devices if row.name == device), devices)

    assert target is not None
    assert target.label == expected


def test_move_to_device_is_none_without_a_peer_at_the_site() -> None:
    lonely = DeviceRow(
        name="rb01-ams01", description="Amsterdam edge router 1", role="edge", status="active", site="ams01"
    )

    assert move_to_device(lonely, parse_devices(build_q1())) is None


def test_message_without_a_peer_device_names_the_device_to_clear() -> None:
    data = build_q1({"rb01-par01": "maintenance"})
    data["DcimDevice"]["edges"] = [
        edge for edge in data["DcimDevice"]["edges"] if edge["node"]["name"]["value"] != "rb02-par01"
    ]

    result = evaluate(data, build_q1(), PARIS)

    assert result.errors[0].endswith("Move these services off Paris edge router 1 first.")


def _without_device(data: dict[str, Any], device: str, services: Collection[str] | None = None) -> dict[str, Any]:
    """Drop the interfaces on `device` from the services (all of them by default), as deleting it would."""
    for edge in data["ServiceDedicatedInternet"]["edges"]:
        node = edge["node"]
        if services is None or node["service_identifier"]["value"] in services:
            interfaces = node["dedicated_interfaces"]
            interfaces["edges"] = [
                interface
                for interface in interfaces["edges"]
                if interface["node"]["device"]["node"]["name"]["value"] != device
            ]
    if services is None:
        data["DcimDevice"]["edges"] = [
            edge for edge in data["DcimDevice"]["edges"] if edge["node"]["name"]["value"] != device
        ]
    return data


def test_deleting_a_device_in_the_path_of_gold_services_fails() -> None:
    """Deleting the router removes its interfaces, so no device behind the service has a status to check."""
    result = evaluate(_without_device(build_q1(), "rb01-par01"), build_q1(), PARIS)

    assert result.errors == [PARIS_MESSAGE]


def test_removing_the_switch_port_of_a_gold_service_fails() -> None:
    result = evaluate(_without_device(build_q1(), "sw01-bru01", {"DI-2001"}), build_q1(), BRUSSELS)

    assert result.errors == [BRUSSELS_MESSAGE]


def test_moving_gold_services_to_the_other_router_passes() -> None:
    """The services still have an edge router: the change only replaces it."""
    branch = build_q1({"rb01-par01": "maintenance"})
    for edge in branch["ServiceDedicatedInternet"]["edges"]:
        for interface in edge["node"]["dedicated_interfaces"]["edges"]:
            device = interface["node"]["device"]["node"]
            if device["name"]["value"] == "rb01-par01":
                device["name"]["value"] = "rb02-par01"
                device["description"]["value"] = "Paris edge router 2"
                device["status"]["value"] = "active"

    assert _passed_clean(evaluate(branch, build_q1(), PARIS))


def test_decommissioning_a_gold_service_passes() -> None:
    branch = build_q1()
    branch["ServiceDedicatedInternet"]["edges"] = [
        edge
        for edge in branch["ServiceDedicatedInternet"]["edges"]
        if edge["node"]["service_identifier"]["value"] != "DI-2001"
    ]

    assert _passed_clean(evaluate(branch, build_q1(), "Decommission DI-2001"))


def test_removing_a_device_already_out_of_service_on_main_only_warns() -> None:
    main = build_q1({"sw01-bru01": "maintenance"})
    branch = _without_device(build_q1({"sw01-bru01": "maintenance"}), "sw01-bru01")

    result = evaluate(branch, main, BRUSSELS)

    assert result.errors == []
    assert len(result.warnings) == 1
    assert "Brussels switch 1" in result.warnings[0]


def test_message_never_suggests_a_device_the_change_also_takes_out_of_service() -> None:
    branch = build_q1({"rb01-par01": "maintenance", "rb02-par01": "maintenance"})

    result = evaluate(branch, build_q1(), "Both Paris routers")

    assert len(result.errors) == 1
    assert result.errors[0].endswith("Move these services off Paris edge router 1 and Paris edge router 2 first.")


def test_move_to_device_skips_a_peer_that_is_not_active() -> None:
    devices = parse_devices(build_q1({"rb02-par01": "maintenance"}))

    assert move_to_device(next(row for row in devices if row.name == "rb01-par01"), devices) is None


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"ServiceDedicatedInternet": None, "DcimDevice": None, "ServiceTier": None},
        {"ServiceDedicatedInternet": {"edges": []}, "DcimDevice": {"edges": []}, "ServiceTier": {"edges": []}},
    ],
    ids=["empty", "null blocks", "no services and no tiers"],
)
def test_missing_data_passes_without_crashing(data: dict[str, Any]) -> None:
    assert _passed_clean(evaluate(data, {}, PARIS))


def test_empty_tier_block_still_uses_each_service_tier() -> None:
    """The guard reads tier and credit percentage from each service, so an empty `ServiceTier` block changes nothing."""
    result = evaluate(build_q1({"rb01-par01": "maintenance"}, tiers={}), build_q1(), PARIS)

    assert result.errors == [PARIS_MESSAGE]


def test_messages_use_no_forbidden_word() -> None:
    """No forbidden on-screen word appears in errors or warnings."""
    results = [
        evaluate(build_q1({"rb01-par01": "maintenance"}), build_q1(), PARIS),
        evaluate(build_q1({"sw01-bru01": "maintenance"}), build_q1(), BRUSSELS),
        evaluate(build_q1({"sw01-bru01": "maintenance"}), build_q1({"sw01-bru01": "maintenance"}), NEW_YORK),
    ]
    messages = [message for result in results for message in (*result.errors, *result.warnings)]

    assert messages
    assert not [message for message in messages if FORBIDDEN_COPY.search(message)]


# The check file, as the Infrahub task worker imports it.


class _Client:
    """Stand-in for the SDK client: the stored query by branch, and one open proposed change."""

    def __init__(self, data_by_branch: dict[str, dict[str, Any]], change_name: str | None) -> None:
        self.data_by_branch = data_by_branch
        self.change_name = change_name
        self.reads: list[tuple[str, str]] = []
        self.traversals: list[tuple[str, str, dict[str, object]]] = []
        self.traversal_error: Exception | None = None
        # Service ids the traversal finds no path from, whatever the query says.
        self.no_path_from: set[str] = set()

    async def query_gql_query(self, name: str, branch_name: str, **_: object) -> dict[str, Any]:
        self.reads.append((name, branch_name))
        body = self.data_by_branch[branch_name]
        return body if "errors" in body else {"data": body}

    async def traverse_paths(self, source: str, destination: str, **kwargs: object) -> object:
        """Answer from the branch data: a path exists when the service has an interface on the device."""
        self.traversals.append((source, destination, kwargs))
        if self.traversal_error is not None:
            raise self.traversal_error
        body = self.data_by_branch[str(kwargs["branch"])]
        data = body.get("data", body)
        devices = {
            interface["node"]["device"]["node"]["id"]
            for edge in data["ServiceDedicatedInternet"]["edges"]
            if edge["node"]["id"] == source
            for interface in edge["node"]["dedicated_interfaces"]["edges"]
        }
        reachable = destination in devices and source not in self.no_path_from
        return type("PathTraversalResult", (), {"count": 1 if reachable else 0})()

    async def filters(self, **_: object) -> list[object]:
        if self.change_name is None:
            return []
        name = type("Attr", (), {"value": self.change_name})()
        return [type("ProposedChange", (), {"name": name})()]


def _run_check(client: _Client, branch: str) -> GoldOutageGuard:
    check = GoldOutageGuard(branch=branch, client=cast("InfrahubClient", client))
    asyncio.run(check.run())
    return check


def test_check_logs_errors_and_reads_main_through_the_client() -> None:
    client = _Client({"maint-rb01-par01": build_q1({"rb01-par01": "maintenance"}), "main": build_q1()}, PARIS)

    check = _run_check(client, "maint-rb01-par01")

    assert not check.passed
    assert [log["message"] for log in check.errors] == [PARIS_MESSAGE]
    assert client.reads == [("business_impact_services", "maint-rb01-par01"), ("business_impact_services", "main")]


def test_check_logs_warnings_as_info_and_passes() -> None:
    main = build_q1({"sw01-bru01": "maintenance"})
    client = _Client({"maint-rb01-nyc01": build_q1({"sw01-bru01": "maintenance"}), "main": main}, None)

    check = _run_check(client, "maint-rb01-nyc01")

    assert check.passed
    infos = [log["message"] for log in check.logs if log["level"] == "INFO"]
    assert any("DI-2001" in message for message in infos)


@pytest.mark.parametrize("failing", ["maint-rb01-par01", "main"])
def test_check_fails_when_a_query_returns_errors(failing: str) -> None:
    """A rejected query must not read as "no Gold service affected"."""
    data = {"maint-rb01-par01": build_q1({"rb01-par01": "maintenance"}), "main": build_q1()}
    data[failing] = {"errors": [{"message": "query refused"}]}

    check = _run_check(_Client(data, PARIS), "maint-rb01-par01")

    assert not check.passed
    assert any("query refused" in log["message"] for log in check.errors)


def test_pass_summary_records_the_exposure_at_approval_time() -> None:
    result = evaluate(build_q1({"rb01-nyc01": "maintenance"}), build_q1(), NEW_YORK)

    assert result.summary == (
        "New York router 1 maintenance leaves no active Gold service without a path. "
        "Gold SLA credit exposure: €0 per month (demo business input)."
    )


def test_no_pass_summary_on_a_failure_or_a_warning() -> None:
    failed = evaluate(build_q1({"rb01-par01": "maintenance"}), build_q1(), PARIS)
    warned = evaluate(build_q1({"sw01-bru01": "maintenance"}), build_q1({"sw01-bru01": "maintenance"}), NEW_YORK)

    assert failed.summary is None
    assert warned.warnings
    assert warned.summary is None


def test_check_logs_the_pass_summary() -> None:
    client = _Client({"maint-rb01-nyc01": build_q1({"rb01-nyc01": "maintenance"}), "main": build_q1()}, NEW_YORK)

    check = _run_check(client, "maint-rb01-nyc01")

    assert check.passed
    infos = [log["message"] for log in check.logs if log["level"] == "INFO"]
    assert any(message.startswith("New York router 1 maintenance leaves no active Gold service") for message in infos)


def test_traversal_pairs_join_each_active_gold_service_to_each_device_out_of_service() -> None:
    pairs = traversal_pairs(build_q1({"rb01-par01": "maintenance"}))

    assert {(pair.service, pair.device) for pair in pairs} == {
        (service, "rb01-par01") for service in ("DI-1001", "DI-1002", "DI-1003", "DI-2001", "DI-2002")
    }
    assert all(pair.service_id == f"service-{pair.service}" for pair in pairs)
    assert all(pair.device_id == "device-rb01-par01" for pair in pairs)


def test_traversal_pairs_are_empty_when_every_device_is_active() -> None:
    assert traversal_pairs(build_q1()) == []


def test_reached_devices_decide_which_services_depend_on_the_device() -> None:
    """With `reached`, the devices behind the service's interfaces in the query are not used."""
    branch = build_q1({"rb01-par01": "maintenance"})

    assert evaluate(branch, build_q1(), PARIS, {"DI-1001": {"rb01-par01"}, "DI-1002": {"rb01-par01"}}).errors == [
        PARIS_MESSAGE
    ]
    assert evaluate(branch, build_q1(), PARIS, {}).passed


def test_check_traces_each_pair_on_the_branch_with_the_network_kinds() -> None:
    client = _Client({"maint-rb01-par01": build_q1({"rb01-par01": "maintenance"}), "main": build_q1()}, PARIS)

    _run_check(client, "maint-rb01-par01")

    assert len(client.traversals) == 5
    assert {kwargs["branch"] for _, _, kwargs in client.traversals} == {"maint-rb01-par01"}
    assert {tuple(cast("list[str]", kwargs["kind_filter"])) for _, _, kwargs in client.traversals} == {NETWORK_KINDS}
    assert {kwargs["max_depth"] for _, _, kwargs in client.traversals} == {MAX_HOPS}


def test_check_passes_when_the_traversal_finds_no_path() -> None:
    """The traversal, not the interface list in the query, decides whether a Gold service depends on the device."""
    client = _Client({"maint-rb01-par01": build_q1({"rb01-par01": "maintenance"}), "main": build_q1()}, PARIS)
    client.no_path_from = {"service-DI-1001", "service-DI-1002"}

    check = _run_check(client, "maint-rb01-par01")

    assert check.passed


def test_check_fails_when_the_traversal_raises() -> None:
    client = _Client({"maint-rb01-par01": build_q1({"rb01-par01": "maintenance"}), "main": build_q1()}, PARIS)
    client.traversal_error = GraphQLError(errors=[{"message": "path traversal refused"}])

    check = _run_check(client, "maint-rb01-par01")

    assert not check.passed
    assert next(log["message"] for log in check.errors).startswith(
        "Gold outage guard could not trace the service paths:"
    )


def test_check_fails_when_the_branch_query_returns_errors_next_to_partial_data() -> None:
    """Errors next to partial data must fail the check: the SDK passes only `data` to `validate`."""
    partial = {"data": build_q1(), "errors": [{"message": "DcimDevice could not be read"}]}
    client = _Client({"maint-rb01-par01": partial, "main": build_q1()}, PARIS)

    check = _run_check(client, "maint-rb01-par01")

    assert not check.passed
    assert [log["message"] for log in check.errors] == [
        "Gold outage guard could not read the proposed change: DcimDevice could not be read"
    ]


def test_worker_imports_the_rule_from_the_commit_worktree(tmp_path: Path) -> None:
    """Infrahub 1.11.4 imports `commits.<sha>.checks.gold_outage_guard` with only the repository directory on
    sys.path (git/integrator.py `execute_python_check`, git/base.py `extract_repo_file_information`), so the
    check must reach `service_catalog` inside the same worktree, not an installed copy.
    """
    worktree = tmp_path / "commits" / "0f1e2d3c"
    shutil.copytree(REPO_ROOT / "checks", worktree / "checks")
    shutil.copytree(
        REPO_ROOT / "service_catalog" / "business_impact",
        worktree / "service_catalog" / "business_impact",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (worktree / "service_catalog" / "__init__.py").write_text("")
    sys.path.append(str(tmp_path))
    try:
        module = importlib.import_module("commits.0f1e2d3c.checks.gold_outage_guard")
        rule = module.load_rule()

        assert rule.__name__ == "commits.0f1e2d3c.service_catalog.business_impact.gold_outage_guard"
        assert rule.__file__.startswith(str(worktree))
    finally:
        sys.path.remove(str(tmp_path))
        for name in [name for name in sys.modules if name == "commits" or name.startswith("commits.")]:
            del sys.modules[name]
