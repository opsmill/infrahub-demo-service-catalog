"""Unit tests for the seed task data and its pure helpers.

The expected rows below are the seed services the docs describe, so a change
to `SEED_SERVICES` that drifts from the documented figures fails here.
Tier multipliers are read from `data/10_customers_tiers.yml`, the file the
repository loads, so the charges stay in line with the seeded price list.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

from service_catalog.business_impact import seed
from service_catalog.business_impact.seed import (
    MAINTENANCE_CHANGES,
    SEED_SERVICES,
    DeviceInfo,
    PortRow,
    ProposedChangeRow,
    SeedError,
    ValidatorRow,
    allocation_problems,
    choose_free_port,
    failed_validators,
    has_core_port,
    missing_repository_items,
    monthly_charge,
    pick_open_proposed_change,
    pipeline_report,
    validators_finished,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TIERS_FILE = REPO_ROOT / "data" / "10_customers_tiers.yml"
DEVICE_TEMPLATE_FILE = REPO_ROOT / "data" / "07_device_template.yml"

# (service, customer, tier, bandwidth Mbps, switch, edge router, monthly charge EUR), from spec.md
SPEC_SEED_TABLE: list[tuple[str, str, str, int, str, str, int]] = [
    ("DI-1001", "Northbank", "Gold", 10000, "sw01-par01", "rb01-par01", 8100),
    ("DI-1002", "Northbank", "Gold", 1000, "sw01-par01", "rb01-par01", 2160),
    ("DI-1003", "Helix Health", "Gold", 1000, "sw02-par01", "rb02-par01", 2160),
    ("DI-1004", "Maison Verte", "Silver", 1000, "sw01-par01", "rb01-par01", 1560),
    ("DI-1005", "Maison Verte", "Silver", 100, "sw02-par01", "rb02-par01", 520),
    ("DI-1006", "Rapid Freight", "Bronze", 100, "sw01-par01", "rb01-par01", 400),
    ("DI-1007", "Rapid Freight", "Bronze", 1000, "sw02-par01", "rb02-par01", 1200),
    ("DI-2001", "Helix Health", "Gold", 10000, "sw01-bru01", "rb01-bru01", 8100),
    ("DI-2002", "Northbank", "Gold", 1000, "sw02-bru01", "rb02-bru01", 2160),
    ("DI-2003", "Maison Verte", "Silver", 1000, "sw01-bru01", "rb01-bru01", 1560),
    ("DI-2004", "Rapid Freight", "Bronze", 100, "sw02-bru01", "rb02-bru01", 400),
    ("DI-2005", "Rapid Freight", "Bronze", 1000, "sw01-bru01", "rb01-bru01", 1200),
]


# (service, requested_by, request_reason), from data-model.md
REQUEST_RECORDS: list[tuple[str, str, str]] = [
    ("DI-1001", "Northbank network operations", "Primary internet access for the Paris trading floor"),
    ("DI-1002", "Northbank network operations", "Internet access for the Paris back office"),
    ("DI-1003", "Helix Health IT infrastructure", "Internet access for the Paris clinic"),
    ("DI-1004", "Maison Verte IT", "Internet access for the Paris flagship store"),
    ("DI-1005", "Maison Verte IT", "Internet access for the Paris warehouse"),
    ("DI-1006", "Rapid Freight logistics IT", "Internet access for the Paris depot"),
    ("DI-1007", "Rapid Freight logistics IT", "Internet access for the Paris sorting centre"),
    ("DI-2001", "Helix Health IT infrastructure", "Primary internet access for the Brussels hospital"),
    ("DI-2002", "Northbank network operations", "Internet access for the Brussels branch"),
    ("DI-2003", "Maison Verte IT", "Internet access for the Brussels store"),
    ("DI-2004", "Rapid Freight logistics IT", "Internet access for the Brussels depot"),
    ("DI-2005", "Rapid Freight logistics IT", "Internet access for the Brussels cross-dock"),
]


def _tier_rows() -> list[dict[str, Any]]:
    documents = list(yaml.safe_load_all(TIERS_FILE.read_text()))
    tiers = next(doc for doc in documents if doc["spec"]["kind"] == "ServiceTier")
    return list(tiers["spec"]["data"])


def _tier_multipliers() -> dict[str, int]:
    return {row["name"]: int(row["price_multiplier_pct"]) for row in _tier_rows()}


def _customer_ports_per_switch() -> int:
    documents = list(yaml.safe_load_all(DEVICE_TEMPLATE_FILE.read_text()))
    templates = documents[0]["spec"]["data"]
    switch = next(row for row in templates if row["role"] == "core")
    return sum(1 for port in switch["interfaces"]["data"] if port["role"] == "customer")


# The seed table


def test_seed_services_match_spec_table() -> None:
    actual = [
        (
            row.service_identifier,
            row.customer,
            row.tier,
            row.bandwidth_mbps,
            row.switch,
            row.edge_router,
            row.monthly_charge,
        )
        for row in SEED_SERVICES
    ]
    assert actual == SPEC_SEED_TABLE


def test_every_service_has_a_request_record() -> None:
    for row in SEED_SERVICES:
        assert row.requested_by.strip(), row
        assert row.request_reason.strip(), row
    actual = [(row.service_identifier, row.requested_by, row.request_reason) for row in SEED_SERVICES]
    assert actual == REQUEST_RECORDS


def test_tier_rules() -> None:
    assert {row["name"]: row.get("min_paths") for row in _tier_rows()} == {"Gold": 1, "Silver": 0, "Bronze": 0}


def test_monthly_charge_follows_price_list() -> None:
    multipliers = _tier_multipliers()
    for row in SEED_SERVICES:
        assert row.monthly_charge == monthly_charge(row.bandwidth_mbps, multipliers[row.tier]), row


def test_monthly_charge_base_prices() -> None:
    assert monthly_charge(100, 100) == 400
    assert monthly_charge(1000, 100) == 1200
    assert monthly_charge(10000, 100) == 4500
    assert monthly_charge(10000, 180) == 8100
    with pytest.raises(ValueError, match="bandwidth"):
        monthly_charge(500, 100)


def test_at_most_six_services_per_switch() -> None:
    ports = _customer_ports_per_switch()
    assert ports == 6
    per_switch = Counter(row.switch for row in SEED_SERVICES)
    assert max(per_switch.values()) <= ports


def test_every_row_uses_small_package_and_order_form_fields() -> None:
    assert {row.ip_package for row in SEED_SERVICES} == {"small"}
    for row in SEED_SERVICES:
        assert row.site == row.switch.split("-", 1)[1]
        assert row.edge_router.split("-", 1)[1] == row.site


def test_twelve_small_packages_fit_the_prefix_pool() -> None:
    # One /24 pool; a /29 package uses 8 addresses.
    assert len(SEED_SERVICES) * 8 <= 256


def test_maintenance_changes() -> None:
    assert [(c.branch, c.device, c.proposed_change_name, c.guard_blocks) for c in MAINTENANCE_CHANGES] == [
        ("maint-rb01-par01", "rb01-par01", "Paris router 1 maintenance", True),
        ("maint-sw01-bru01", "sw01-bru01", "Brussels switch 1 maintenance", True),
        # A site with no active service, so the Gold outage guard passes.
        ("maint-rb01-nyc01", "rb01-nyc01", "New York router 1 maintenance", False),
        # The same maintenance after the Gold services are moved, so the Gold outage guard passes.
        ("maint-rb01-par01-moved", "rb01-par01", "Paris router 1 maintenance, Gold services moved first", False),
    ]
    assert all(change.description for change in MAINTENANCE_CHANGES)


def test_only_the_moved_plan_moves_services() -> None:
    assert [change.moves for change in MAINTENANCE_CHANGES] == [
        (),
        (),
        (),
        (("DI-1001", "sw02-par01"), ("DI-1002", "sw02-par01")),
    ]


def test_moved_plan_covers_every_gold_service_behind_paris_edge_router_1() -> None:
    """Every Gold service behind rb01-par01 moves to switch 2, whose edge router has the same index (rb02-par01)."""
    moved = MAINTENANCE_CHANGES[3]
    gold_behind_router = {
        row.service_identifier for row in SEED_SERVICES if row.tier == "Gold" and row.edge_router == moved.device
    }

    assert {service for service, _ in moved.moves} == gold_behind_router
    assert {switch for _, switch in moved.moves} == {"sw02-par01"}


def test_generator_command_runs_on_the_given_branch() -> None:
    assert seed.generator_command("DI-1001") == (
        "infrahubctl generator dedicated_internet_generator service_identifier=DI-1001 --branch main"
    )
    assert seed.generator_command("DI-1001", "maint-rb01-par01-moved").endswith("--branch maint-rb01-par01-moved")


GUARD = seed.GUARD_VALIDATOR_LABEL


def test_pipeline_report_names_the_guard_failure_as_expected_on_a_blocking_change() -> None:
    paris = MAINTENANCE_CHANGES[0]
    rows = [ValidatorRow("Data", "completed", "success"), ValidatorRow(GUARD, "completed", "failure")]

    assert pipeline_report(paris, rows) == [
        f"Paris router 1 maintenance: {GUARD} failed, as expected; the merge is blocked"
    ]


def test_pipeline_report_names_the_guard_pass_as_expected_on_new_york() -> None:
    new_york = MAINTENANCE_CHANGES[2]

    assert pipeline_report(new_york, [ValidatorRow(GUARD, "completed", "success")]) == [
        f"New York router 1 maintenance: {GUARD} passed, as expected"
    ]


def test_pipeline_report_flags_unexpected_results_and_other_failures() -> None:
    paris, new_york = MAINTENANCE_CHANGES[0], MAINTENANCE_CHANGES[2]

    assert pipeline_report(paris, [ValidatorRow(GUARD, "completed", "success")]) == [
        f"Paris router 1 maintenance: unexpected, {GUARD} concluded success"
    ]
    assert pipeline_report(new_york, [ValidatorRow(GUARD, "completed", "failure")]) == [
        f"New York router 1 maintenance: unexpected, {GUARD} failed"
    ]
    assert pipeline_report(new_york, [ValidatorRow("Generator", "completed", "failure")]) == [
        f"New York router 1 maintenance: unexpected, no {GUARD} validator",
        "New York router 1 maintenance: validator Generator concluded failure",
    ]


# Pure helpers


def test_choose_free_port_takes_lowest_free_customer_port() -> None:
    ports = [
        PortRow(id="p10", name="Ethernet10", role="customer", status="free", service_id=None),
        PortRow(id="p4", name="Ethernet4", role="customer", status="active", service_id="other"),
        PortRow(id="p5", name="Ethernet5", role="customer", status="free", service_id="other"),
        PortRow(id="p1", name="Ethernet1", role="uplink", status="free", service_id=None),
        PortRow(id="p7", name="Ethernet7", role="customer", status="free", service_id=None),
        PortRow(id="p6", name="Ethernet6", role="customer", status="active", service_id=None),
    ]
    chosen = choose_free_port(ports)
    assert chosen is not None
    assert chosen.id == "p7"


def test_choose_free_port_returns_none_when_switch_is_full() -> None:
    ports = [PortRow(id="p4", name="Ethernet4", role="customer", status="active", service_id="s")]
    assert choose_free_port(ports) is None


def test_has_core_port() -> None:
    devices = {"sw": DeviceInfo(name="sw01-par01", role="core"), "rb": DeviceInfo(name="rb01-par01", role="edge")}
    assert has_core_port(["rb", "sw"], devices) is True
    assert has_core_port(["rb"], devices) is False
    assert has_core_port([], devices) is False


DEVICES = {
    "sw1": DeviceInfo(name="sw01-par01", role="core"),
    "sw2": DeviceInfo(name="sw02-par01", role="core"),
    "rb1": DeviceInfo(name="rb01-par01", role="edge"),
    "rb2": DeviceInfo(name="rb02-par01", role="edge"),
}


def test_allocation_problems_none_when_complete() -> None:
    row = SEED_SERVICES[0]  # DI-1001 on sw01-par01 / rb01-par01
    assert (
        allocation_problems(row, port_device_ids=["sw1"], gateway_device_ids=["rb1"], vlan_count=1, devices=DEVICES)
        == []
    )


@pytest.mark.parametrize(
    ("ports", "gateways", "vlans", "expected"),
    [
        ([], ["rb1"], 1, "core port"),
        (["sw1", "sw1"], ["rb1"], 1, "core port"),
        (["sw2"], ["rb1"], 1, "sw01-par01"),
        (["sw1"], [], 1, "gateway"),
        (["sw1"], ["rb2"], 1, "rb01-par01"),
        (["sw1"], ["rb1"], 0, "VLAN"),
    ],
)
def test_allocation_problems_name_what_is_missing(
    ports: list[str], gateways: list[str], vlans: int, expected: str
) -> None:
    row = SEED_SERVICES[0]
    problems = allocation_problems(
        row, port_device_ids=ports, gateway_device_ids=gateways, vlan_count=vlans, devices=DEVICES
    )
    assert problems
    assert any(expected in problem for problem in problems), problems


def test_missing_repository_items() -> None:
    complete: dict[str, Any] = {
        "tiers": ["Gold", "Silver", "Bronze"],
        "customers": ["Northbank", "Helix Health", "Maison Verte", "Rapid Freight"],
        "queries": ["business_impact_services", "dedicated_internet_info"],
        "generators": ["dedicated_internet_generator"],
    }
    assert missing_repository_items(**complete) == []
    partial = {**complete, "customers": ["Northbank"], "queries": []}
    missing = missing_repository_items(**partial)
    assert "customer Helix Health" in missing
    assert "query business_impact_services" in missing
    assert len(missing) == 4


def test_validators_finished_needs_at_least_one_validator() -> None:
    assert validators_finished([]) is False
    assert validators_finished([ValidatorRow("Data", "completed", "success")]) is True
    assert (
        validators_finished(
            [ValidatorRow("Data", "completed", "success"), ValidatorRow("Gen", "in_progress", "unknown")]
        )
        is False
    )


def test_validators_finished_waits_for_required_labels() -> None:
    data = ValidatorRow("Data", "completed", "success")
    guard = ValidatorRow(seed.GUARD_VALIDATOR_LABEL, "completed", "failure")

    assert validators_finished([data], required=[seed.GUARD_VALIDATOR_LABEL]) is False
    assert validators_finished([data, guard], required=[seed.GUARD_VALIDATOR_LABEL]) is True


def test_failed_validators() -> None:
    rows = [
        ValidatorRow("Data", "completed", "success"),
        ValidatorRow("Generator", "completed", "failure"),
        ValidatorRow(None, "completed", "failure"),
    ]
    assert failed_validators(rows) == ["Generator", "(no label)"]


def test_pick_open_proposed_change_reuses_open_one_for_the_branch() -> None:
    change = MAINTENANCE_CHANGES[0]
    rows = [
        ProposedChangeRow(id="closed", name=change.proposed_change_name, state="closed", source_branch=change.branch),
        ProposedChangeRow(id="other", name=change.proposed_change_name, state="open", source_branch="elsewhere"),
        ProposedChangeRow(id="open", name=change.proposed_change_name, state="open", source_branch=change.branch),
    ]
    assert pick_open_proposed_change(rows, change) == "open"
    assert pick_open_proposed_change(rows[:2], change) is None


def test_wait_until_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 0.0}

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(seed.time, "sleep", fake_sleep)
    monkeypatch.setattr(seed.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(seed, "POLL_INTERVAL_S", 5.0)
    calls: list[float] = []

    def never() -> bool:
        calls.append(clock["now"])
        return False

    with pytest.raises(SeedError, match="the thing"):
        seed.wait_until(never, timeout_s=20.0, what="the thing")
    assert calls == [0.0, 5.0, 10.0, 15.0, 20.0]


def test_wait_until_returns_when_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed.time, "sleep", lambda _seconds: None)
    answers = iter([False, False, True])
    seed.wait_until(lambda: next(answers), timeout_s=600.0, what="ready")


def test_run_generators_stops_on_first_failing_command() -> None:
    commands: list[str] = []

    def run(command: str) -> None:
        commands.append(command)
        raise SeedError(f"failed: {command}")

    with pytest.raises(SeedError, match="DI-1001"):
        seed.run_generators(client=object(), run=run)
    assert commands == [
        "infrahubctl generator dedicated_internet_generator service_identifier=DI-1001 --branch main",
    ]


def test_seed_module_builds_no_client_at_import() -> None:
    assert "client" not in vars(seed)
    assert callable(seed.build_client)
