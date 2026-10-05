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
from service_catalog.business_impact.blast_radius import DeviceRow, parse_devices
from service_catalog.business_impact.gold_outage_guard import GuardResult, evaluate, move_to_device
from tests.unit.test_blast_radius import FORBIDDEN_COPY, REPO_ROOT, SEED, build_q1

if TYPE_CHECKING:
    from pathlib import Path

    from infrahub_sdk import InfrahubClient

PARIS = "Paris router 1 maintenance"
BRUSSELS = "Brussels switch 1 maintenance"
NEW_YORK = "New York router 1 maintenance"

PARIS_MESSAGE = (
    "Paris router 1 maintenance takes 2 Gold services for Northbank out of service (DI-1001, DI-1002). "
    "Gold SLA credit exposure: €2,565 per month (demo business input). "
    "Move these services to Paris edge router 2 first."
)
BRUSSELS_MESSAGE = (
    "Brussels switch 1 maintenance takes 1 Gold service for Helix Health out of service (DI-2001). "
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
        "Two sites takes 3 Gold services for Helix Health and Northbank out of service (DI-1001, DI-1002, DI-2001). "
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

    async def query_gql_query(self, name: str, branch_name: str, **_: object) -> dict[str, Any]:
        self.reads.append((name, branch_name))
        body = self.data_by_branch[branch_name]
        return body if "errors" in body else {"data": body}

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
