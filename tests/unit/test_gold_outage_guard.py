"""Unit tests for the Gold outage guard rule.

Runs `evaluate` on the seed-shaped query fixture of `builders.py`: the
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

from checks.gold_outage_guard import MESSAGE_WIDTH, GoldOutageGuard
from service_catalog.business_impact.blast_radius import (
    DeviceRow,
    parse_devices,
    paths,
    paths_up,
)
from service_catalog.business_impact.gold_outage_guard import GuardResult, evaluate, move_to_device
from tests.unit.builders import (
    BRUSSELS,
    BRUSSELS_MESSAGE,
    FORBIDDEN_COPY,
    MONEY_WORDS,
    NEW_YORK,
    PARIS,
    RAISE_SILVER,
    RAISE_SILVER_MESSAGE,
    REPO_ROOT,
    SEED,
    QueryClient,
    SeedRow,
    build_q1,
    build_seeded_q1,
    service_row,
    traced,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    from infrahub_sdk import InfrahubClient

PARIS_MESSAGE = (
    "Paris router 1 maintenance leaves 2 Gold services for Northbank with no other path (DI-1001, DI-1002). "
    "Each has 1 separate path on the current network and 0 during this change. "
    "Move these services to Paris edge router 2 first. "
    "Gold requires at least 1 separate path during a change, and this change leaves 0."
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


@pytest.mark.parametrize("tier", ["Silver", None], ids=["silver-or-bronze-only", "unassigned-tier"])
def test_no_gold_service_behind_the_device_passes(tier: str | None) -> None:
    """The Gold services become Silver, or have no tier: no Gold service is behind the device."""
    rows = tuple(replace(row, tier=tier) if row.tier == "Gold" else row for row in SEED)

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
        "Each has 1 separate path on the current network and 0 during this change. "
        "Move these services to Brussels switch 2 and Paris edge router 2 first. "
        "Gold requires at least 1 separate path during a change, and this change leaves 0."
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
    """Paris has no edge router 2 here, and no service depends on it."""
    rows = tuple(row for row in SEED if row.router != "rb02-par01")
    data = build_q1({"rb01-par01": "maintenance"}, rows=rows)
    data["DcimDevice"]["edges"] = [
        edge for edge in data["DcimDevice"]["edges"] if edge["node"]["name"]["value"] != "rb02-par01"
    ]

    result = evaluate(traced(data), build_q1(rows=rows), PARIS)

    assert result.errors[0].endswith(
        "Move these services off Paris edge router 1 first. "
        "Gold requires at least 1 separate path during a change, and this change leaves 0."
    )


def _without_device(data: dict[str, Any], device: str, services: Collection[str] | None = None) -> dict[str, Any]:
    """Drop the interfaces on `device` from the services (all of them by default), as deleting it would.

    The footprints are traced again, so the services no longer reach the device.
    """
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
    return traced(data)


def test_deleting_a_device_in_the_path_of_gold_services_fails() -> None:
    """Deleting the router removes its interfaces, so no device behind the service has a status to check."""
    result = evaluate(_without_device(build_q1(), "rb01-par01"), build_q1(), PARIS)

    assert result.errors == [PARIS_MESSAGE]


def test_removing_the_switch_port_of_a_gold_service_fails() -> None:
    result = evaluate(_without_device(build_q1(), "sw01-bru01", {"DI-2001"}), build_q1(), BRUSSELS)

    assert result.errors == [BRUSSELS_MESSAGE]


def test_moving_gold_services_to_the_other_router_passes() -> None:
    """The services move to switch 2 and edge router 2, so each keeps a path: the change only replaces it."""
    branch = build_q1({"rb01-par01": "maintenance"})
    moves = {"rb01-par01": "rb02-par01", "sw01-par01": "sw02-par01"}
    for edge in branch["ServiceDedicatedInternet"]["edges"]:
        for interface in edge["node"]["dedicated_interfaces"]["edges"]:
            device = interface["node"]["device"]["node"]
            if device["name"]["value"] in moves:
                device["name"]["value"] = moves[device["name"]["value"]]

    assert _passed_clean(evaluate(traced(branch), build_q1(), PARIS))


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
    assert result.errors[0].endswith(
        "Move these services off Paris edge router 1 and Paris edge router 2 first. "
        "Gold requires at least 1 separate path during a change, and this change leaves 0."
    )


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
    assert _passed_clean(evaluate(traced(data), traced({}), PARIS))


def test_data_without_footprints_is_refused() -> None:
    """Each service's devices come from its footprint, so a query result without footprints cannot be read."""
    plain = {key: block for key, block in build_q1().items() if key != "footprints"}

    with pytest.raises(ValueError, match="no service footprints"):
        evaluate(plain, build_q1(), PARIS)


def test_empty_tier_block_still_uses_each_service_tier() -> None:
    """The guard reads the tier from each service, so an empty `ServiceTier` block changes nothing."""
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


# The rule read from the service tier.


def test_rule_comes_from_the_tier() -> None:
    """Gold 0 and Silver 1: only the Silver service behind the router fails, with the Silver rule sentence."""
    rules = {"Gold": 0, "Silver": 1, "Bronze": 0}

    result = evaluate(build_q1({"rb01-par01": "maintenance"}, min_paths=rules), build_q1(min_paths=rules), PARIS)

    assert len(result.errors) == 1
    assert "(DI-1004)" in result.errors[0]
    assert result.errors[0].startswith("Paris router 1 maintenance leaves 1 Silver service for Maison Verte")
    assert result.errors[0].endswith(
        "Silver requires at least 1 separate path during a change, and this change leaves 0."
    )
    assert result.warnings == []

    gold_off = {"Gold": 0, "Silver": 0, "Bronze": 0}
    assert _passed_clean(
        evaluate(build_q1({"rb01-par01": "maintenance"}, min_paths=gold_off), build_q1(min_paths=gold_off), PARIS)
    )


def test_path_count() -> None:
    """1 path with an active switch and router; 0 when either is not active or the router's interface is gone."""
    active = service_row(build_q1(), "DI-2001")
    switch_down = service_row(build_q1({"sw01-bru01": "maintenance"}), "DI-2001")
    router_down = service_row(build_q1({"rb01-bru01": "maintenance"}), "DI-2001")
    no_router = service_row(_without_device(build_q1(), "rb01-bru01"), "DI-2001")

    assert paths_up(active) == 1
    assert paths_up(switch_down) == 0
    assert paths_up(router_down) == 0
    assert paths_up(no_router) == 0
    # The roles come from the row as queried, so the path counts without reading the device statuses.
    assert len(paths(active)) == 1


def test_silver_with_rule_one_fails() -> None:
    rules = {"Gold": 1, "Silver": 1, "Bronze": 0}

    result = evaluate(build_q1({"sw01-bru01": "maintenance"}, min_paths=rules), build_q1(min_paths=rules), BRUSSELS)

    assert result.errors[0] == BRUSSELS_MESSAGE
    assert len(result.errors) == 2
    assert result.errors[1] == (
        "Brussels switch 1 maintenance leaves 1 Silver service for Maison Verte with no other path (DI-2003). "
        "It has 1 separate path on the current network and 0 during this change. "
        "Move this service to Brussels switch 2 first. "
        "Silver requires at least 1 separate path during a change, and this change leaves 0."
    )


def test_empty_rule_reads_as_zero() -> None:
    rules: dict[str, int | None] = {"Gold": None, "Silver": 0, "Bronze": 0}

    result = evaluate(build_q1({"rb01-par01": "maintenance"}, min_paths=rules), build_q1(min_paths=rules), PARIS)

    assert _passed_clean(result)


def test_second_device_behind_a_service_already_without_path_only_warns() -> None:
    """DI-2001 has 0 paths on main and 0 on the branch, so the second device changes nothing for it."""
    main = build_q1({"sw01-bru01": "maintenance"})
    branch = build_q1({"sw01-bru01": "maintenance", "rb01-bru01": "maintenance"})

    result = evaluate(branch, main, "Brussels router 1 maintenance")

    assert result.errors == []
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("WARNING: Gold service DI-2001 for Helix Health is already out of service")


def test_service_new_on_the_branch_is_checked_against_the_branch_rule() -> None:
    """A service missing on main counts as meeting the rule on main, so it fails on the branch rule alone."""
    new = SeedRow("DI-1008", "Northbank", "Gold", "1000", "sw02-par01", "rb01-par01")

    result = evaluate(build_q1({"rb01-par01": "maintenance"}, rows=(new,)), build_q1(rows=()), PARIS)

    assert result.errors == [
        "Paris router 1 maintenance leaves 1 Gold service for Northbank with no other path (DI-1008). "
        "It becomes active in this change and has 0 separate paths. "
        "Move this service to Paris edge router 2 first. "
        "Gold requires at least 1 separate path during a change, and this change leaves 0."
    ]


def test_service_not_active_on_main_is_checked_against_the_branch_rule() -> None:
    """A draft service on main has no paths to lose: a change that activates it short of the rule fails."""
    main = build_q1()
    service = next(
        edge["node"]
        for edge in main["ServiceDedicatedInternet"]["edges"]
        if edge["node"]["service_identifier"]["value"] == "DI-1001"
    )
    service["status"]["value"] = "draft"

    result = evaluate(build_q1({"rb01-par01": "maintenance"}), main, PARIS)

    assert result.warnings == []
    assert [error for error in result.errors if "DI-1001" in error]
    assert "becomes active in this change" in next(error for error in result.errors if "DI-1001" in error)


def _without_interfaces(data: dict[str, Any], identifier: str) -> dict[str, Any]:
    """Drop every dedicated interface of the service, as before its generator runs."""
    for edge in data["ServiceDedicatedInternet"]["edges"]:
        if edge["node"]["service_identifier"]["value"] == identifier:
            edge["node"]["dedicated_interfaces"]["edges"] = []
    return data


def test_service_new_on_the_branch_without_interfaces_fails_with_no_move_sentence() -> None:
    """No device sits behind the new service, so the message names none and goes on to the rule."""
    new = SeedRow("DI-1008", "Northbank", "Gold", "1000", "sw02-par01", "rb01-par01")
    branch = _without_interfaces(build_q1(rows=(new,)), "DI-1008")

    result = evaluate(branch, build_q1(rows=()), "Order DI-1008")

    assert result.errors == [
        "Order DI-1008 leaves 1 Gold service for Northbank with no other path (DI-1008). "
        "It becomes active in this change and has 0 separate paths. "
        "Gold requires at least 1 separate path during a change, and this change leaves 0."
    ]
    assert result.warnings == []


def test_service_without_a_switch_or_edge_router_on_main_and_the_branch_is_left_out() -> None:
    """The service has no path to lose and the change took none away, so the guard stays silent."""
    branch = _without_interfaces(build_q1({"rb01-nyc01": "maintenance"}), "DI-2001")
    main = _without_interfaces(build_q1(), "DI-2001")

    result = evaluate(branch, main, NEW_YORK)

    assert result.errors == []
    assert result.warnings == []
    assert result.summary == (
        "New York router 1 maintenance leaves every active Gold service with at least 1 separate path."
    )


# A change that raises a tier rule.


def _rules(silver: int, gold: int = 1) -> dict[str, int | None]:
    return {"Gold": gold, "Silver": silver, "Bronze": 0}


def test_raising_silver_to_two_fails() -> None:
    result = evaluate(build_q1(min_paths=_rules(2)), build_q1(min_paths=_rules(0)), RAISE_SILVER)

    assert not result.passed
    assert result.errors == [RAISE_SILVER_MESSAGE]
    assert result.warnings == []


def test_tightening_message() -> None:
    """With `sw01-bru01` in maintenance, DI-2003 has 0 paths and the other Silver services have 1."""
    out = {"sw01-bru01": "maintenance"}

    to_one = evaluate(build_q1(out, min_paths=_rules(1)), build_q1(out, min_paths=_rules(0)), RAISE_SILVER)
    to_two = evaluate(build_q1(out, min_paths=_rules(2)), build_q1(out, min_paths=_rules(0)), RAISE_SILVER)

    assert to_one.errors == [
        "Promise two paths to Silver customers raises the Silver rule from 0 to 1 separate path during a change, "
        "and 1 active Silver service has fewer (DI-2003: 0). Build the paths first, or keep the rule at 0."
    ]
    assert to_two.errors == [
        "Promise two paths to Silver customers raises the Silver rule from 0 to 2 separate paths during a change, "
        "and 3 active Silver services have fewer (DI-1004: 1, DI-1005: 1, DI-2003: 0). "
        "Build the paths first, or keep the rule at 0."
    ]


def test_tightening_error_comes_after_the_path_errors() -> None:
    """The raised Silver services get no path error; the Gold path error comes first."""
    out = {"sw01-bru01": "maintenance"}

    result = evaluate(build_q1(out, min_paths=_rules(1)), build_q1(min_paths=_rules(0)), BRUSSELS)

    assert len(result.errors) == 2
    assert result.errors[0] == BRUSSELS_MESSAGE
    assert result.errors[1].startswith("Brussels switch 1 maintenance raises the Silver rule from 0 to 1")
    assert "(DI-2003: 0)" in result.errors[1]


def test_lowering_a_rule_passes() -> None:
    result = evaluate(build_q1(min_paths=_rules(0, gold=0)), build_q1(min_paths=_rules(0)), "Lower the Gold rule")

    assert _passed_clean(result)
    assert result.summary == ("Lower the Gold rule leaves every active Gold service with at least 0 separate paths.")


def test_raising_silver_to_one_passes() -> None:
    """Every Silver service already has 1 path."""
    result = evaluate(build_q1(min_paths=_rules(1)), build_q1(min_paths=_rules(0)), RAISE_SILVER)

    assert _passed_clean(result)


def test_new_tier_is_not_a_tightening() -> None:
    """Silver is missing on main, so its branch rule applies on both sides and the router gives a path error."""
    main_tiers = ("Gold", "Bronze")
    branch = build_q1({"rb01-par01": "maintenance"}, min_paths=_rules(1))

    result = evaluate(branch, build_q1(tiers=main_tiers, min_paths=_rules(0)), PARIS)

    assert result.errors[0] == PARIS_MESSAGE
    assert len(result.errors) == 2
    assert result.errors[1].startswith("Paris router 1 maintenance leaves 1 Silver service for Maison Verte")
    assert all("raises the" not in error for error in result.errors)


# The check file, as the Infrahub task worker imports it.


def _text(log: dict) -> str:
    """A logged message with its line breaks turned back into spaces."""
    return str(log["message"]).replace("\n", " ")


def _run_check(client: QueryClient, branch: str) -> GoldOutageGuard:
    check = GoldOutageGuard(branch=branch, client=cast("InfrahubClient", client))
    asyncio.run(check.run())
    return check


def test_check_logs_errors_and_reads_main_through_the_client() -> None:
    client = QueryClient({"maint-rb01-par01": build_q1({"rb01-par01": "maintenance"}), "main": build_q1()}, PARIS)

    check = _run_check(client, "maint-rb01-par01")

    assert not check.passed
    assert [_text(log) for log in check.errors] == [PARIS_MESSAGE]
    assert client.reads == [("business_impact_services", "maint-rb01-par01"), ("business_impact_services", "main")]


def test_check_messages_fit_the_infrahub_message_box() -> None:
    """Infrahub does not wrap a check message, so each line stays short and the service IDs stay whole."""
    client = QueryClient({"maint-rb01-par01": build_q1({"rb01-par01": "maintenance"}), "main": build_q1()}, PARIS)

    check = _run_check(client, "maint-rb01-par01")

    lines = [line for log in check.logs for line in str(log["message"]).splitlines()]
    assert len(lines) > 1
    assert all(len(line) <= MESSAGE_WIDTH for line in lines)
    assert any("DI-" in line for line in lines)
    assert not [line for line in lines if line.endswith("DI-")]


def test_check_logs_warnings_as_info_and_passes() -> None:
    main = build_q1({"sw01-bru01": "maintenance"})
    client = QueryClient({"maint-rb01-nyc01": build_q1({"sw01-bru01": "maintenance"}), "main": main}, None)

    check = _run_check(client, "maint-rb01-nyc01")

    assert check.passed
    infos = [_text(log) for log in check.logs if log["level"] == "INFO"]
    assert any("DI-2001" in message for message in infos)


@pytest.mark.parametrize("failing", ["maint-rb01-par01", "main"])
def test_check_fails_when_a_query_returns_errors(failing: str) -> None:
    """A rejected query must not read as "no Gold service affected"."""
    data = {"maint-rb01-par01": build_q1({"rb01-par01": "maintenance"}), "main": build_q1()}
    data[failing] = {"errors": [{"message": "query refused"}]}

    check = _run_check(QueryClient(data, PARIS), "maint-rb01-par01")

    assert not check.passed
    assert any("query refused" in _text(log) for log in check.errors)


def test_pass_summary_records_the_exposure_at_approval_time() -> None:
    result = evaluate(build_q1({"rb01-nyc01": "maintenance"}), build_q1(), NEW_YORK)

    assert result.summary == (
        "New York router 1 maintenance leaves every active Gold service with at least 1 separate path."
    )


def test_no_pass_summary_on_a_failure_or_a_warning() -> None:
    failed = evaluate(build_q1({"rb01-par01": "maintenance"}), build_q1(), PARIS)
    warned = evaluate(build_q1({"sw01-bru01": "maintenance"}), build_q1({"sw01-bru01": "maintenance"}), NEW_YORK)

    assert failed.summary is None
    assert warned.warnings
    assert warned.summary is None


def test_check_logs_the_pass_summary() -> None:
    client = QueryClient({"maint-rb01-nyc01": build_q1({"rb01-nyc01": "maintenance"}), "main": build_q1()}, NEW_YORK)

    check = _run_check(client, "maint-rb01-nyc01")

    assert check.passed
    infos = [_text(log) for log in check.logs if log["level"] == "INFO"]
    assert any(
        message.startswith("New York router 1 maintenance leaves every active Gold service") for message in infos
    )


def test_check_fails_when_the_branch_query_returns_errors_next_to_partial_data() -> None:
    """Errors next to partial data must fail the check: the SDK passes only `data` to `validate`."""
    partial = {"data": build_q1(), "errors": [{"message": "DcimDevice could not be read"}]}
    client = QueryClient({"maint-rb01-par01": partial, "main": build_q1()}, PARIS)

    check = _run_check(client, "maint-rb01-par01")

    assert not check.passed
    assert [_text(log) for log in check.errors] == [
        "Gold outage guard could not read the proposed change: DcimDevice could not be read"
    ]


def test_worker_imports_the_rule_from_the_commit_worktree(commit_worktree: Path) -> None:
    """Infrahub 1.11.4 imports `commits.<sha>.checks.gold_outage_guard` with only the repository directory on
    sys.path (git/integrator.py `execute_python_check`, git/base.py `extract_repo_file_information`), so the
    check must reach `service_catalog` inside the same worktree, not an installed copy.
    """
    worktree = commit_worktree
    package = f"commits.{worktree.name}"
    shutil.copytree(REPO_ROOT / "checks", worktree / "checks")
    shutil.copytree(REPO_ROOT / "transforms", worktree / "transforms", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(
        REPO_ROOT / "service_catalog" / "business_impact",
        worktree / "service_catalog" / "business_impact",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for name in ("network.py", "protocols_async.py"):
        shutil.copy(REPO_ROOT / "service_catalog" / name, worktree / "service_catalog" / name)
    module = importlib.import_module(f"{package}.checks.gold_outage_guard")
    impact = module.load_impact()

    assert impact.__name__ == f"{package}.service_catalog.business_impact.change_impact"
    assert impact.__file__.startswith(str(worktree))
    for name in ("gold_outage_guard", "blast_radius", "footprint"):
        loaded = sys.modules[f"{package}.service_catalog.business_impact.{name}"]
        assert str(loaded.__file__).startswith(str(worktree))
    assert str(sys.modules[f"{package}.service_catalog.network"].__file__).startswith(str(worktree))


# Services with two separate paths, as `invoke seed` builds the Paris Gold services.


def test_path_count_with_two_paths() -> None:
    """Each switch and edge router pair with the same index is a path; one device out leaves the other."""
    both = service_row(build_seeded_q1(), "DI-1001")
    one_out = service_row(build_seeded_q1({"rb01-par01": "maintenance"}), "DI-1001")
    both_out = service_row(build_seeded_q1({"rb01-par01": "maintenance", "sw02-par01": "maintenance"}), "DI-1001")

    assert paths_up(both) == 2
    assert paths_up(one_out) == 1
    assert paths_up(both_out) == 0
    # Without the device statuses, both paths count.
    assert len(paths(one_out)) == 2


def test_two_paths_with_one_device_out_passes() -> None:
    result = evaluate(build_seeded_q1({"rb01-par01": "maintenance"}), build_seeded_q1(), PARIS)

    assert _passed_clean(result)
    assert (
        result.summary == "Paris router 1 maintenance leaves every active Gold service with at least 1 separate path."
    )


def test_two_paths_with_both_devices_out_fails() -> None:
    branch = build_seeded_q1({"rb01-par01": "maintenance", "rb02-par01": "maintenance"})

    result = evaluate(branch, build_seeded_q1(), "Both Paris routers")

    assert result.errors == [
        "Both Paris routers leaves 3 Gold services for Helix Health and Northbank with no other path "
        "(DI-1001, DI-1002, DI-1003). "
        "Each has 2 separate paths on the current network and 0 during this change. "
        "Move these services off Paris edge router 1 and Paris edge router 2 first. "
        "Gold requires at least 1 separate path during a change, and this change leaves 0."
    ]


def test_branch_that_deletes_one_of_two_switch_ports_passes() -> None:
    """DI-1001 keeps the path through switch 2 and edge router 2."""
    branch = _without_device(build_seeded_q1(), "sw01-par01", {"DI-1001"})

    assert len(paths(service_row(branch, "DI-1001"))) == 1
    assert _passed_clean(evaluate(branch, build_seeded_q1(), "Remove a port of DI-1001"))


def test_branch_that_deletes_both_switch_ports_fails() -> None:
    branch = _without_device(_without_device(build_seeded_q1(), "sw01-par01", {"DI-1001"}), "sw02-par01", {"DI-1001"})

    result = evaluate(branch, build_seeded_q1(), "Remove the ports of DI-1001")

    assert len(result.errors) == 1
    assert result.errors[0].startswith(
        "Remove the ports of DI-1001 leaves 1 Gold service for Northbank with no other path (DI-1001). "
        "It has 2 separate paths on the current network and 0 during this change. "
    )
    assert result.errors[0].endswith(
        "Gold requires at least 1 separate path during a change, and this change leaves 0."
    )


def test_messages_contain_no_money_or_sla_figure() -> None:
    results = [
        evaluate(build_q1({"sw01-bru01": "maintenance"}), build_q1(), BRUSSELS),
        evaluate(build_seeded_q1({"rb01-par01": "maintenance", "rb02-par01": "maintenance"}), build_seeded_q1(), PARIS),
        evaluate(build_seeded_q1({"rb01-par01": "maintenance"}), build_seeded_q1(), PARIS),
        evaluate(build_q1({"sw01-bru01": "maintenance"}), build_q1({"sw01-bru01": "maintenance"}), NEW_YORK),
        evaluate(build_q1(min_paths=_rules(2)), build_q1(min_paths=_rules(0)), RAISE_SILVER),
    ]
    messages = [
        message
        for result in results
        for message in (*result.errors, *result.warnings, *([result.summary] if result.summary else []))
    ]

    assert len(messages) == 5
    for word in ("EUR", "€", "SLA", "credit"):
        assert not [message for message in messages if word in message]
    assert not [message for message in messages if MONEY_WORDS.search(message)]


def test_check_passes_on_the_seeded_paris_router_1_maintenance() -> None:
    client = QueryClient(
        {"maint-rb01-par01": build_seeded_q1({"rb01-par01": "maintenance"}), "main": build_seeded_q1()}, PARIS
    )

    check = _run_check(client, "maint-rb01-par01")

    assert check.passed
    infos = [_text(log) for log in check.logs if log["level"] == "INFO"]
    assert "Paris router 1 maintenance leaves every active Gold service with at least 1 separate path." in infos
