"""Unit tests for the seed task data and its pure helpers.

The expected rows below are the seed services the docs describe, so a change
to `SEED_SERVICES` that drifts from the documented figures fails here.
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml

from service_catalog.business_impact import seed
from service_catalog.business_impact.seed import (
    MAINTENANCE_CHANGES,
    SECOND_PATHS,
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
    pick_open_proposed_change,
    pipeline_report,
    repository_import_action,
    validators_finished,
)

from .builders import REPO_ROOT, sdk_value

TIERS_FILE = REPO_ROOT / "data" / "10_customers_tiers.yml"
DEVICE_TEMPLATE_FILE = REPO_ROOT / "data" / "07_device_template.yml"

# (service, customer, tier, bandwidth Mbps, switch, edge router): the services the seed creates
SPEC_SEED_TABLE: list[tuple[str, str, str, int, str, str]] = [
    ("DI-1001", "Northbank", "Gold", 10000, "sw01-par01", "rb01-par01"),
    ("DI-1002", "Northbank", "Gold", 1000, "sw01-par01", "rb01-par01"),
    ("DI-1003", "Helix Health", "Gold", 1000, "sw02-par01", "rb02-par01"),
    ("DI-1004", "Maison Verte", "Silver", 1000, "sw01-par01", "rb01-par01"),
    ("DI-1005", "Maison Verte", "Silver", 100, "sw02-par01", "rb02-par01"),
    ("DI-1006", "Rapid Freight", "Bronze", 100, "sw01-par01", "rb01-par01"),
    ("DI-1007", "Rapid Freight", "Bronze", 1000, "sw02-par01", "rb02-par01"),
    ("DI-2001", "Helix Health", "Gold", 10000, "sw01-bru01", "rb01-bru01"),
    ("DI-2002", "Northbank", "Gold", 1000, "sw02-bru01", "rb02-bru01"),
    ("DI-2003", "Maison Verte", "Silver", 1000, "sw01-bru01", "rb01-bru01"),
    ("DI-2004", "Rapid Freight", "Bronze", 100, "sw02-bru01", "rb02-bru01"),
    ("DI-2005", "Rapid Freight", "Bronze", 1000, "sw01-bru01", "rb01-bru01"),
]


# (service, requested_by, request_reason), as the seed list records them
REQUEST_RECORDS: list[tuple[str, str, str]] = [
    ("DI-1001", "Northbank network operations", "Primary internet access for the Paris trading floor"),
    ("DI-1002", "Northbank network operations", "Internet access for the Paris back office"),
    ("DI-1003", "Helix Health IT infrastructure", "Internet access for the Paris clinic"),
    ("DI-1004", "Maison Verte IT", "Internet access for the Paris flagship store"),
    ("DI-1005", "Maison Verte IT", "Internet access for the Paris warehouse"),
    ("DI-1006", "Rapid Freight logistics IT", "Internet access for the Paris depot"),
    ("DI-1007", "Rapid Freight logistics IT", "Internet access for the Paris sorting centre"),
    ("DI-2001", "Helix Health IT infrastructure", "Primary internet access for the Brussels hospital"),
    ("DI-2002", "Northbank network operations", "Internet access for the Brussels office"),
    ("DI-2003", "Maison Verte IT", "Internet access for the Brussels store"),
    ("DI-2004", "Rapid Freight logistics IT", "Internet access for the Brussels depot"),
    ("DI-2005", "Rapid Freight logistics IT", "Internet access for the Brussels cross-dock"),
]


def _tier_rows() -> list[dict[str, Any]]:
    documents = list(yaml.safe_load_all(TIERS_FILE.read_text()))
    tiers = next(doc for doc in documents if doc["spec"]["kind"] == "ServiceTier")
    return list(tiers["spec"]["data"])


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


def test_the_seed_writes_no_money() -> None:
    """Services carry no charge: the seed has no price table and writes no monthly charge."""
    assert not hasattr(seed, "BASE_PRICE_EUR")
    assert not hasattr(seed, "TIER_MULTIPLIER_PCT")
    assert not hasattr(seed, "monthly_charge")
    assert not hasattr(SEED_SERVICES[0], "monthly_charge")


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
        # Every Paris Gold service keeps its second path through rb02-par01, so the guard passes.
        ("maint-rb01-par01", "rb01-par01", "Paris router 1 maintenance", False),
        # DI-2001 has a single path through sw01-bru01, so the guard fails.
        ("maint-sw01-bru01", "sw01-bru01", "Brussels switch 1 maintenance", True),
        # A site with no active service, so the Gold outage guard passes.
        ("maint-rb01-nyc01", "rb01-nyc01", "New York router 1 maintenance", False),
    ]
    assert all(change.description for change in MAINTENANCE_CHANGES)


def test_no_change_moves_services() -> None:
    assert not hasattr(seed, "move_services")
    assert not any("moved" in change.branch or "moved" in change.proposed_change_name for change in MAINTENANCE_CHANGES)


def test_second_path_plan() -> None:
    """DI-1001 and DI-1002 get a path through switch 2, DI-1003 through switch 1; Brussels keeps one path."""
    assert [(path.service_identifier, path.switch, path.edge_router) for path in SECOND_PATHS] == [
        ("DI-1001", "sw02-par01", "rb02-par01"),
        ("DI-1002", "sw02-par01", "rb02-par01"),
        ("DI-1003", "sw01-par01", "rb01-par01"),
    ]
    by_service = {row.service_identifier: row for row in SEED_SERVICES}
    for path in SECOND_PATHS:
        row = by_service[path.service_identifier]
        assert row.tier == "Gold"
        assert row.site == "par01"
        # The other switch and the edge router with the same index.
        assert path.switch != row.switch
        assert path.switch[:4] == path.edge_router.replace("rb", "sw")[:4]
    paris_gold = {row.service_identifier for row in SEED_SERVICES if row.tier == "Gold" and row.site == "par01"}
    assert {path.service_identifier for path in SECOND_PATHS} == paris_gold


def test_switches_have_room_for_the_second_paths() -> None:
    per_switch = Counter(row.switch for row in SEED_SERVICES)
    per_switch.update(path.switch for path in SECOND_PATHS)
    assert max(per_switch.values()) <= _customer_ports_per_switch()


def test_generator_command_runs_on_the_given_branch() -> None:
    assert seed.generator_command("DI-1001") == (
        "infrahubctl generator dedicated_internet_generator service_identifier=DI-1001 --branch main"
    )
    assert seed.generator_command("DI-1001", "maint-rb01-par01").endswith("--branch maint-rb01-par01")


GUARD = seed.GUARD_VALIDATOR_LABEL


def test_pipeline_report_names_the_guard_failure_as_expected_on_a_blocking_change() -> None:
    brussels = MAINTENANCE_CHANGES[1]
    rows = [ValidatorRow("Data", "completed", "success"), ValidatorRow(GUARD, "completed", "failure")]

    assert pipeline_report(brussels, rows) == [
        f"Brussels switch 1 maintenance: {GUARD} failed, as expected; the merge is blocked"
    ]


@pytest.mark.parametrize(
    ("index", "name"),
    [(0, "Paris router 1 maintenance"), (2, "New York router 1 maintenance")],
    ids=["paris", "new-york"],
)
def test_pipeline_report_names_the_guard_pass_as_expected(index: int, name: str) -> None:
    change = MAINTENANCE_CHANGES[index]

    assert pipeline_report(change, [ValidatorRow(GUARD, "completed", "success")]) == [
        f"{name}: {GUARD} passed, as expected"
    ]


def test_pipeline_report_flags_unexpected_results_and_other_failures() -> None:
    brussels, new_york = MAINTENANCE_CHANGES[1], MAINTENANCE_CHANGES[2]

    assert pipeline_report(brussels, [ValidatorRow(GUARD, "completed", "success")]) == [
        f"Brussels switch 1 maintenance: unexpected, {GUARD} concluded success"
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


def test_allocation_problems_accept_the_second_path_from_an_earlier_seed_run() -> None:
    di_1001, di_1003 = SEED_SERVICES[0], SEED_SERVICES[2]
    for row in (di_1001, di_1003):
        problems = allocation_problems(
            row, port_device_ids=["sw2", "sw1"], gateway_device_ids=["rb1", "rb2"], vlan_count=1, devices=DEVICES
        )
        assert problems == [], row
    # DI-1003's first path is on switch 2; switch 1 alone is not its first path.
    problems = allocation_problems(
        di_1003, port_device_ids=["sw1"], gateway_device_ids=["rb2"], vlan_count=1, devices=DEVICES
    )
    assert any("sw02-par01" in problem for problem in problems), problems


def test_allocation_problems_reject_a_second_path_on_a_single_path_service() -> None:
    di_1004 = SEED_SERVICES[3]  # Silver, sw01-par01 / rb01-par01, no second path
    problems = allocation_problems(
        di_1004, port_device_ids=["sw1", "sw2"], gateway_device_ids=["rb1"], vlan_count=1, devices=DEVICES
    )
    assert problems == ["expected one core port, found 2"]


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


@pytest.mark.parametrize(
    ("sync_status", "action"),
    [
        ("in-sync", "done"),
        ("error-import", "reimport"),
        ("syncing", "wait"),
        ("unknown", "wait"),
    ],
)
def test_repository_import_action(sync_status: str, action: str) -> None:
    """The seed goes on only when the repository is in sync, and imports again after an import error."""
    assert repository_import_action(sync_status) == action


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


def test_wait_until_times_out(monkeypatch: pytest.MonkeyPatch, clock: dict[str, float]) -> None:
    monkeypatch.setattr(seed, "POLL_INTERVAL_S", 5.0)
    calls: list[float] = []

    def never() -> bool:
        calls.append(clock["now"])
        return False

    with pytest.raises(SeedError, match="the thing"):
        seed.wait_until(never, timeout_s=20.0, what="the thing")
    assert calls == [0.0, 5.0, 10.0, 15.0, 20.0]


@pytest.mark.usefixtures("clock")
def test_wait_until_returns_when_ready() -> None:
    answers = iter([False, False, True])
    seed.wait_until(lambda: next(answers), timeout_s=600.0, what="ready")


# The wait for the cost of service artifact

CSV_HEADER_ONLY = "service,customer\n"
CSV_WITH_ROWS = "service,customer\nDI-1001,Northbank\n"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    """A clock that `time.sleep` moves forward, so the waits take no real time."""
    now = {"now": 0.0}
    monkeypatch.setattr(seed.time, "sleep", lambda seconds: now.update(now=now["now"] + seconds))
    monkeypatch.setattr(seed.time, "monotonic", lambda: now["now"])
    return now


def _cost_wait(
    monkeypatch: pytest.MonkeyPatch, clock: dict[str, float], before: str | None, contents: dict[float, str | None]
) -> list[float]:
    """Wait for the artifact; `contents` gives its content from each time on. Return the times of the resends."""
    monkeypatch.setattr(
        seed, "_cost_csv", lambda _client: contents[max(time for time in contents if time <= clock["now"])]
    )
    resends: list[float] = []
    definition = SimpleNamespace(generate=lambda: resends.append(clock["now"]))
    seed.wait_for_cost_of_service(cast("Any", object()), seed.CostRequest(definition, before, 0.0))
    return resends


def test_cost_wait_ends_when_the_artifact_changes(monkeypatch: pytest.MonkeyPatch, clock: dict[str, float]) -> None:
    resends = _cost_wait(monkeypatch, clock, CSV_HEADER_ONLY, {0.0: CSV_HEADER_ONLY, 3.0: CSV_WITH_ROWS})

    assert resends == []
    assert clock["now"] == pytest.approx(3.0)


def test_cost_wait_resends_once_then_accepts_an_unchanged_artifact_with_rows(
    monkeypatch: pytest.MonkeyPatch, clock: dict[str, float]
) -> None:
    """A second seed run: Infrahub renders the same CSV again and keeps the artifact as it is."""
    resends = _cost_wait(monkeypatch, clock, CSV_WITH_ROWS, {0.0: CSV_WITH_ROWS})

    assert resends == [seed.ARTIFACT_RESEND_S]
    assert clock["now"] == pytest.approx(2 * seed.ARTIFACT_RESEND_S)


def test_cost_wait_times_out_on_an_artifact_without_rows(
    monkeypatch: pytest.MonkeyPatch, clock: dict[str, float]
) -> None:
    with pytest.raises(SeedError, match="Step 2: Timed out"):
        _cost_wait(monkeypatch, clock, CSV_HEADER_ONLY, {0.0: CSV_HEADER_ONLY})


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


# add_second_paths with a fake client


class FakeNode(SimpleNamespace):
    def save(self, **kwargs: Any) -> None:  # noqa: ANN401 - mirrors the SDK keyword arguments
        self.saves.append(kwargs)


class FakeClient:
    """Paris devices, the three Paris Gold services after their generator run, and six ports per switch."""

    def __init__(self) -> None:
        self.devices = [
            FakeNode(id=name, name=sdk_value(name), role=sdk_value(role), saves=[])
            for name, role in [
                ("sw01-par01", "core"),
                ("sw02-par01", "core"),
                ("rb01-par01", "edge"),
                ("rb02-par01", "edge"),
            ]
        ]
        first_paths = {"DI-1001": "sw01-par01", "DI-1002": "sw01-par01", "DI-1003": "sw02-par01"}
        self.services = {
            identifier: FakeNode(id=identifier, bandwidth=sdk_value("1000"), saves=[]) for identifier in first_paths
        }
        self.vlans = [
            FakeNode(id=f"vlan-{identifier}", vlan_id=sdk_value(100 + index), service=SimpleNamespace(id=identifier))
            for index, identifier in enumerate(first_paths)
        ]
        self.ports = [
            FakeNode(
                id=f"{switch}-Ethernet{number}",
                name=sdk_value(f"Ethernet{number}"),
                device=SimpleNamespace(id=switch),
                role=sdk_value("customer"),
                status=sdk_value("free"),
                service=SimpleNamespace(id=None),
                enabled=sdk_value(False),
                l2_mode=sdk_value(None),
                description=sdk_value(None),
                speed=sdk_value(None),
                untagged_vlan=None,
                saves=[],
            )
            for switch in ("sw01-par01", "sw02-par01")
            for number in range(3, 9)
        ]
        for identifier, switch in first_paths.items():
            port = next(p for p in self.ports if p.device.id == switch and p.service.id is None)
            port.service = self.services[identifier]
            port.status.value = "active"
        self.created: list[FakeNode] = []

    def all(self, kind: type, branch: str) -> list[FakeNode]:
        assert kind.__name__ == "DcimDevice"
        return self.devices

    def get(self, kind: type, service_identifier__value: str, branch: str) -> FakeNode:
        return self.services[service_identifier__value]

    def filters(self, kind: type, branch: str, **filters: list[str]) -> list[FakeNode]:
        nodes = {"DcimInterfaceL2": self.ports, "IpamVLAN": self.vlans}[kind.__name__]
        if "service__ids" in filters:
            return [node for node in nodes if node.service.id in filters["service__ids"]]
        return [node for node in nodes if node.device.id in filters["device__ids"]]

    def create(self, kind: type, branch: str, **data: Any) -> FakeNode:  # noqa: ANN401 - node data
        assert kind.__name__ == "DcimInterfaceL3"
        node = FakeNode(kind=kind.__name__, branch=branch, data=data, saves=[])
        self.created.append(node)
        return node


def test_add_second_paths_adds_a_port_and_a_gateway_per_paris_gold_service() -> None:
    client = FakeClient()

    seed.add_second_paths(client)

    second_ports = {
        port.service.id: port
        for port in client.ports
        if port.description.value and "Second path" in port.description.value
    }
    assert {identifier: port.device.id for identifier, port in second_ports.items()} == {
        "DI-1001": "sw02-par01",
        "DI-1002": "sw02-par01",
        "DI-1003": "sw01-par01",
    }
    for identifier, port in second_ports.items():
        vlan = next(vlan for vlan in client.vlans if vlan.service.id == identifier)
        assert port.status.value == "active"
        assert port.enabled.value is True
        assert port.l2_mode.value == "Access"
        assert port.role.value == "customer"
        assert port.speed.value == 1000
        assert port.untagged_vlan is vlan
        assert port.saves == [{"allow_upsert": True}]

    assert [
        (node.data["name"], node.data["device"], node.data["service"].id, node.data["status"], node.data["role"])
        for node in client.created
    ] == [
        ("vlan_100", {"id": "rb02-par01"}, "DI-1001", "active", "customer"),
        ("vlan_101", {"id": "rb02-par01"}, "DI-1002", "active", "customer"),
        ("vlan_102", {"id": "rb01-par01"}, "DI-1003", "active", "customer"),
    ]
    for node in client.created:
        assert node.data["enabled"] is True
        assert not {"ip_addresses", "address"} & set(node.data)
        assert node.saves == [{"allow_upsert": True}]


def test_add_second_paths_runs_again_without_changes() -> None:
    client = FakeClient()
    seed.add_second_paths(client)
    saves_after_first_run = [list(port.saves) for port in client.ports]

    seed.add_second_paths(client)

    assert len(client.created) == 3
    assert [port.saves for port in client.ports] == saves_after_first_run


def test_add_second_paths_takes_the_lowest_free_port_on_the_other_switch() -> None:
    client = FakeClient()

    seed.add_second_paths(client)

    taken = sorted((port.device.id, port.name.value) for port in client.ports if port.description.value is not None)
    # sw01-par01 Ethernet3 and 4 hold DI-1001 and DI-1002; sw02-par01 Ethernet3 holds DI-1003.
    assert taken == [("sw01-par01", "Ethernet5"), ("sw02-par01", "Ethernet4"), ("sw02-par01", "Ethernet5")]


# The descriptions of the repository items


class _DescribedNode:
    """A repository item as the SDK returns it: its name and description, and the number of saves."""

    def __init__(self, name: str, description: str | None) -> None:
        self.name = sdk_value(name)
        self.description = sdk_value(description)
        self.saves = 0

    def save(self) -> None:
        self.saves += 1


def _describe_client(descriptions: dict[tuple[type, str], str | None]) -> tuple[Any, dict[tuple[type, str], Any]]:
    """A client that returns one node per (kind, name), with the given description."""
    found = {key: _DescribedNode(key[1], description) for key, description in descriptions.items()}
    client = SimpleNamespace(
        filters=lambda kind, name__value, **_: [
            node for (k, n), node in found.items() if k is kind and n == name__value
        ]
    )
    return client, found


def test_every_repository_description_is_one_plain_sentence() -> None:
    for (_, name), description in seed.REPOSITORY_DESCRIPTIONS.items():
        assert description.endswith("."), name
        assert description.count(". ") == 0, name
        assert "—" not in description, name


def test_describe_repository_items_names_the_check_generator_artifacts_and_queries() -> None:
    names = {(kind.__name__, name) for kind, name in seed.REPOSITORY_DESCRIPTIONS}

    assert names == {
        ("CoreCheckDefinition", "gold_outage_guard"),
        ("CoreGeneratorDefinition", "dedicated_internet_generator"),
        ("CoreArtifactDefinition", "Affected customers"),
        ("CoreArtifactDefinition", "Cost of service"),
        ("CoreArtifactDefinition", "Startup Config"),
        ("CoreGraphQLQuery", "business_impact_services"),
        ("CoreGraphQLQuery", "cost_of_service"),
        ("CoreGraphQLQuery", "dedicated_internet_info"),
        ("CoreGraphQLQuery", "device_info"),
    }


def test_repository_items_named_in_infrahub_yml() -> None:
    config = yaml.safe_load((REPO_ROOT / ".infrahub.yml").read_text(encoding="utf-8"))
    in_config = {
        "CoreCheckDefinition": {item["name"] for item in config["check_definitions"]},
        "CoreGeneratorDefinition": {item["name"] for item in config["generator_definitions"]},
        "CoreArtifactDefinition": {item["name"] for item in config["artifact_definitions"]},
        "CoreGraphQLQuery": {item["name"] for item in config["queries"]},
    }

    for kind, name in seed.REPOSITORY_DESCRIPTIONS:
        assert name in in_config[kind.__name__], (kind.__name__, name)


def test_describe_repository_items_sets_each_empty_description() -> None:
    client, found = _describe_client(dict.fromkeys(seed.REPOSITORY_DESCRIPTIONS))

    seed.describe_repository_items(cast("Any", client))

    for key, node in found.items():
        assert (node.description.value, node.saves) == (seed.REPOSITORY_DESCRIPTIONS[key], 1)


def test_describe_repository_items_saves_nothing_when_the_descriptions_match() -> None:
    client, found = _describe_client(dict(seed.REPOSITORY_DESCRIPTIONS))

    seed.describe_repository_items(cast("Any", client))
    seed.describe_repository_items(cast("Any", client))

    assert [node.saves for node in found.values()] == [0] * len(found)


def test_describe_repository_items_rewrites_only_a_different_description() -> None:
    key = (seed.CoreGraphQLQuery, "device_info")
    client, found = _describe_client({**seed.REPOSITORY_DESCRIPTIONS, key: "An old text"})

    seed.describe_repository_items(cast("Any", client))

    assert {name: node.saves for (_, name), node in found.items() if node.saves} == {"device_info": 1}
    assert found[key].description.value == seed.REPOSITORY_DESCRIPTIONS[key]


def test_describe_repository_items_names_step_1_when_an_item_never_loads(clock: dict[str, float]) -> None:
    descriptions: dict[tuple[type, str], str | None] = dict(seed.REPOSITORY_DESCRIPTIONS)
    del descriptions[seed.CoreCheckDefinition, "gold_outage_guard"]
    client, _ = _describe_client(descriptions)

    with pytest.raises(SeedError, match=r"Step 1: .*CoreCheckDefinition gold_outage_guard"):
        seed.describe_repository_items(cast("Any", client))


def test_run_all_runs_the_steps_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """The descriptions and the circuits come right after the repository wait; the artifact wait comes last."""
    calls: list[str] = []
    request = object()

    def step(name: str, result: object = None) -> Any:  # noqa: ANN401 - stands in for any step
        def record(*args: object) -> object:
            calls.append(name)
            if name == "wait_for_cost_of_service":
                assert args[1] is request
            return result

        return record

    for name in (
        "wait_for_repository",
        "describe_repository_items",
        "load_upstream_circuits",
        "seed_services",
        "run_generators",
        "add_second_paths",
        "ensure_outreach_webhook",
        "seed_maintenance",
        "wait_for_cost_of_service",
    ):
        monkeypatch.setattr(seed, name, step(name))
    monkeypatch.setattr(seed, "request_cost_of_service", step("request_cost_of_service", request))

    seed.run_all(cast("Any", object()), lambda _command: None)

    assert calls == [
        "wait_for_repository",
        "describe_repository_items",
        "load_upstream_circuits",
        "seed_services",
        "run_generators",
        "add_second_paths",
        "request_cost_of_service",
        "ensure_outreach_webhook",
        "seed_maintenance",
        "wait_for_cost_of_service",
    ]


# The circuit schema and the upstream circuits


class _RepositoryClient:
    """A client whose repository reads each status of `statuses` in turn, then the last one."""

    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.reimports: list[dict[str, Any]] = []

    def get(self, kind: object, name__value: str, branch: str) -> SimpleNamespace:
        assert (name__value, branch) == ("infrahub-demo-service-catalog", "main")
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return SimpleNamespace(id="repository-id", sync_status=sdk_value(status))

    def execute_graphql(self, query: str, variables: dict[str, Any], branch_name: str) -> dict[str, Any]:
        assert "InfrahubRepositoryProcess" in query
        self.reimports.append(variables)
        return {}


@pytest.mark.usefixtures("clock")
def test_wait_for_repository_in_sync_waits_while_an_import_runs() -> None:
    client = _RepositoryClient(["unknown", "syncing", "in-sync"])

    seed.wait_for_repository_in_sync(cast("Any", client))

    assert client.reimports == []


@pytest.mark.usefixtures("clock")
def test_wait_for_repository_in_sync_imports_again_after_an_import_error() -> None:
    client = _RepositoryClient(["error-import", "syncing", "syncing", "in-sync"])

    seed.wait_for_repository_in_sync(cast("Any", client))

    assert client.reimports == [{"id": "repository-id"}]


@pytest.mark.usefixtures("clock")
def test_wait_for_repository_in_sync_stops_when_the_import_keeps_failing() -> None:
    statuses = ["error-import", "syncing"] * seed.REIMPORT_ATTEMPTS + ["error-import"]
    client = _RepositoryClient(statuses)

    with pytest.raises(SeedError, match=r"Step 1: the import of repository infrahub-demo-service-catalog failed 3"):
        seed.wait_for_repository_in_sync(cast("Any", client))
    assert len(client.reimports) == seed.REIMPORT_ATTEMPTS


class _CircuitSchemaClient(_RepositoryClient):
    """A client whose main schema has the circuit kind from the `loaded_after`-th schema read on.

    Its repository is in sync.
    """

    def __init__(self, loaded_after: int) -> None:
        super().__init__(["in-sync"])
        self.reads = 0
        self.loaded_after = loaded_after
        self.schema = self

    def all(self, branch: str, refresh: bool = False) -> dict[str, object]:
        assert (branch, refresh) == ("main", True)
        self.reads += 1
        kinds = ["DcimDevice", *(["DcimCircuit"] if self.reads >= self.loaded_after else [])]
        return dict.fromkeys(kinds, object())


@pytest.mark.usefixtures("clock")
def test_load_upstream_circuits_loads_the_schema_then_waits_then_loads_the_menu_and_the_circuits() -> None:
    client = _CircuitSchemaClient(loaded_after=3)
    commands: list[str] = []

    seed.load_upstream_circuits(cast("Any", client), commands.append)

    assert commands == [
        "infrahubctl schema load schemas/circuit --branch main --wait 60",
        "infrahubctl menu load menu_circuit.yml --branch main",
        "infrahubctl object load data/business_impact/upstream_circuits.yml --branch main",
    ]
    assert client.reads == 3


def test_load_upstream_circuits_runs_the_same_commands_again_on_a_rerun() -> None:
    """The schema load and the object load change nothing when the schema and the circuits exist."""
    client = _CircuitSchemaClient(loaded_after=1)
    first: list[str] = []
    second: list[str] = []

    seed.load_upstream_circuits(cast("Any", client), first.append)
    seed.load_upstream_circuits(cast("Any", client), second.append)

    assert first == second


def test_load_upstream_circuits_names_step_1_when_a_command_fails() -> None:
    def fail(command: str) -> None:
        raise SeedError(f"`{command}` exited with code 1")

    with pytest.raises(SeedError, match=r"Step 1: `infrahubctl schema load schemas/circuit"):
        seed.load_upstream_circuits(cast("Any", _CircuitSchemaClient(loaded_after=1)), fail)
