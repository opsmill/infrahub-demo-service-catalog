"""Unit tests of the cost of service figures (`service_catalog/cost_of_service/cost.py`).

The query result is built from the seed: the twelve services of `invoke seed`, the second paths of
the three Paris Gold services, the list prices of `data/06_device_type.yml` and the circuits of
`data/business_impact/upstream_circuits.yml`. Each switch port and each gateway interface of a path
is active, and each edge router's `Ethernet4` is active because it carries the circuit.
"""

from __future__ import annotations

import asyncio
import csv
import importlib
import io
import shutil
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from infrahub_sdk.exceptions import SchemaNotFoundError
from infrahub_sdk.node import InfrahubNode
from service_catalog.cost_of_service.cost import (
    CSV_HEADER,
    NO_ACTIVE_INTERFACES,
    NO_CIRCUIT,
    NO_LIST_PRICE,
    NO_SERVICE_BANDWIDTH,
    ONE_TIME,
    PER_MONTH,
    CostLine,
    cost_lines,
    has_circuits,
    inputs,
    router_bandwidth,
    service_lines,
    services,
    shares,
    to_csv,
    totals,
    with_circuits,
)
from transforms.cost_of_service import CostOfService

from .builders import (
    CIRCUITS,
    REPO_ROOT,
    SEED,
    SEEDED,
    TraversalClient,
    build_circuit_data,
    build_cost_data,
    stored_only,
    traced,
)

if TYPE_CHECKING:
    from pathlib import Path

    from infrahub_sdk import InfrahubClient


def _line(lines: list[CostLine], service: str, path: str, part: str) -> CostLine:
    return next(line for line in lines if line.service == service and line.path.startswith(path) and line.part == part)


# Hand check of the shares from the seeded inputs


def test_active_interface_counts_after_the_seed() -> None:
    devices = {
        (path.switch.name, path.switch.active_interfaces) for service in services(SEEDED) for path in service.paths
    } | {(path.router.name, path.router.active_interfaces) for service in services(SEEDED) for path in service.paths}

    assert sorted(devices) == [
        ("rb01-bru01", 4),
        ("rb01-par01", 6),
        ("rb02-bru01", 3),
        ("rb02-par01", 6),
        ("sw01-bru01", 3),
        ("sw01-par01", 5),
        ("sw02-bru01", 2),
        ("sw02-par01", 5),
    ]


def test_bandwidth_through_each_paris_router_from_the_seed() -> None:
    """rb01-par01: DI-1001 10000, DI-1002 1000, DI-1004 1000, DI-1006 100, DI-1003 1000 (second path).

    rb02-par01: DI-1003 1000, DI-1005 100, DI-1007 1000, DI-1001 10000 and DI-1002 1000 (second paths).
    """
    bandwidth = router_bandwidth(services(SEEDED))

    assert bandwidth["rb01-par01"] == 10000 + 1000 + 1000 + 100 + 1000 == 13100
    assert bandwidth["rb02-par01"] == 1000 + 100 + 1000 + 10000 + 1000 == 13100


def test_di_1001_by_hand() -> None:
    lines = service_lines(cost_lines(SEEDED), "DI-1001")
    circuit_share = 2500 * 10000 / 13100

    assert [(line.path, line.part, line.item, line.input, line.divisor, line.share, line.unit) for line in lines] == [
        ("primary (sw01-par01 / rb01-par01)", "switch", "sw01-par01", 6000, 5, 1200.0, ONE_TIME),
        ("primary (sw01-par01 / rb01-par01)", "router", "rb01-par01", 12000, 6, 2000.0, ONE_TIME),
        ("primary (sw01-par01 / rb01-par01)", "circuit", "COG-PAR-TR-1001", 2500, 13100, circuit_share, PER_MONTH),
        ("backup (sw02-par01 / rb02-par01)", "switch", "sw02-par01", 6000, 5, 1200.0, ONE_TIME),
        ("backup (sw02-par01 / rb02-par01)", "router", "rb02-par01", 12000, 6, 2000.0, ONE_TIME),
        ("backup (sw02-par01 / rb02-par01)", "circuit", "COLT-PAR-TR-2001", 2500, 13100, circuit_share, PER_MONTH),
    ]
    assert round(circuit_share, 2) == pytest.approx(1908.40)
    summed = shares(lines)
    # The sum adds the unrounded shares and rounds once: 2 x 1908.3969 = 3816.79, not 2 x 1908.40.
    assert (summed.hardware, summed.circuit) == (6400.0, 3816.79)


def test_the_backup_path_is_on_the_switch_with_the_higher_index() -> None:
    """DI-1003's first path from the generator is on switch 2, but switch 1 has the lower index."""
    lines = service_lines(cost_lines(SEEDED), "DI-1003")

    assert [line.path for line in lines if line.part == "switch"] == [
        "primary (sw01-par01 / rb01-par01)",
        "backup (sw02-par01 / rb02-par01)",
    ]
    backup = _line(lines, "DI-1003", "backup", "circuit")
    assert (backup.item, backup.share) == ("COLT-PAR-TR-2001", 2500 * 1000 / 13100)


def test_a_one_path_service_has_only_a_primary_path() -> None:
    lines = service_lines(cost_lines(SEEDED), "DI-2001")

    assert {line.path for line in lines} == {"primary (sw01-bru01 / rb01-bru01)"}
    assert [(line.part, line.share) for line in lines] == [
        ("switch", 2000.0),
        ("router", 3000.0),
        ("circuit", 2000 * 10000 / 12000),
    ]


# Edge cases


def test_a_device_with_no_active_interfaces_has_no_share() -> None:
    lines = cost_lines(build_cost_data(active={"sw02-bru01": 0}))
    line = _line(lines, "DI-2002", "primary", "switch")

    assert (line.divisor, line.share, line.note) == (0, None, NO_ACTIVE_INTERFACES)
    assert "nan" not in to_csv(lines)
    assert "inf" not in to_csv(lines)
    assert Counter(line.note for line in lines if line.note) == {NO_ACTIVE_INTERFACES: 2}


def test_a_device_type_with_no_list_price_is_left_out_of_the_totals() -> None:
    data = build_cost_data(prices={"Generic switch": None})
    lines = cost_lines(data)
    line = _line(lines, "DI-1001", "primary", "switch")

    assert (line.input, line.share, line.note) == (None, None, NO_LIST_PRICE)
    assert Counter(line.note for line in lines if line.note) == {NO_LIST_PRICE: 15}
    assert shares(lines).hardware == round(shares(cost_lines(SEEDED)).hardware - _switch_total(SEEDED), 2)


def _switch_total(data: dict[str, Any]) -> float:
    return sum(line.share or 0.0 for line in cost_lines(data) if line.part == "switch")


def test_an_edge_router_with_no_circuit_gives_no_circuit_share() -> None:
    data = build_cost_data(circuits={key: value for key, value in CIRCUITS.items() if key != "rb02-bru01"})
    lines = cost_lines(data)
    line = _line(lines, "DI-2002", "primary", "circuit")

    assert (line.item, line.input, line.share, line.note) == ("", None, None, NO_CIRCUIT)
    assert Counter(line.note for line in lines if line.note) == {NO_CIRCUIT: 2}
    assert shares(lines).circuit == round(shares(cost_lines(SEEDED)).circuit - 2000, 2)
    # With no circuit, the upstream interface of rb02-bru01 is not active, so it carries no share (4000 before).
    assert totals(data).upstream_total == totals(SEEDED).upstream_total - 4000


def test_a_service_that_is_not_active_carries_no_cost() -> None:
    """DI-1001 back to draft: it has no line, and its bandwidth leaves the Paris routers' divisor."""
    rows = tuple(replace(row, status="draft") if row.identifier == "DI-1001" else row for row in SEED)
    data = build_cost_data(rows)
    lines = cost_lines(data)

    assert "DI-1001" not in {service.identifier for service in services(data)}
    assert not service_lines(lines, "DI-1001")
    assert router_bandwidth(services(data))["rb01-par01"] == 13100 - 10000
    assert _line(lines, "DI-1002", "primary", "circuit").share == pytest.approx(2500 * 1000 / 3100)


def test_an_edge_router_with_no_service_bandwidth_gives_a_note_not_a_share() -> None:
    """Both Brussels router 2 services at 0 Mbit/s: their circuit lines have no share and a note."""
    rows = tuple(replace(row, bandwidth="0") if row.router == "rb02-bru01" else row for row in SEED)
    lines = cost_lines(build_cost_data(rows))
    line = _line(lines, "DI-2002", "primary", "circuit")

    assert (line.item, line.divisor, line.share, line.note) == ("COLT-BRU-TR-2001", 0, None, NO_SERVICE_BANDWIDTH)
    assert Counter(line.note for line in lines if line.note) == {NO_SERVICE_BANDWIDTH: 2}
    assert shares(lines).circuit == round(shares(cost_lines(SEEDED)).circuit - 2000, 2)


# Totals


def test_totals_keep_one_time_and_monthly_figures_apart() -> None:
    lines = cost_lines(SEEDED)
    result = shares(lines)

    # Paris: 10 paths at 1200 + 2000. Brussels switch 1: 3 paths at 2000 + 3000. Switch 2: 2 paths at 3000 + 4000.
    assert result.hardware == 10 * 3200 + 3 * 5000 + 2 * 7000 == 61000
    assert result.hardware == round(sum(line.share or 0 for line in lines if line.unit == ONE_TIME), 2)
    # Each router's circuit is split over its paths: 2500 x 2 + 2000 x 2. Rounded once, not per share.
    assert result.circuit == pytest.approx(9000, abs=0.001)
    assert result.circuit == round(sum(line.share or 0 for line in lines if line.unit == PER_MONTH), 2)
    assert not [line for line in lines if line.note]


def test_the_csv_rows_are_rounded_and_the_totals_are_not_added_from_them() -> None:
    """The CSV shows each share to the cent; the total adds the unrounded shares, so it can differ by a cent."""
    lines = cost_lines(SEEDED)
    rows = list(csv.DictReader(io.StringIO(to_csv(lines))))

    assert round(sum(float(row["share"]) for row in rows if row["unit"] == PER_MONTH), 2) == pytest.approx(9000.01)
    assert shares(lines).circuit == pytest.approx(9000, abs=0.001)


def test_the_upstream_interface_share_is_its_own_line() -> None:
    """Not part of the hardware total: list price / active interfaces, once per router that carries services.

    rb01-par01 and rb02-par01: 12000 / 6. rb01-bru01: 12000 / 4. rb02-bru01: 12000 / 3.
    """
    assert totals(SEEDED).upstream_total == 2000 + 2000 + 3000 + 4000 == 11000
    assert shares(cost_lines(SEEDED)).hardware == 61000


def test_edge_routers_that_carry_no_service_are_their_own_line() -> None:
    """The New York and Dallas edge routers carry no service path: their list price, not a share, and not in a total."""
    result = totals(SEEDED)

    assert [(router.router, router.list_price) for router in result.unused_routers] == [
        ("rb01-dal01", 12000),
        ("rb01-nyc01", 12000),
        ("rb02-dal01", 12000),
        ("rb02-nyc01", 12000),
    ]
    assert result.unused_total == 48000


def test_costs_not_carried_by_any_service() -> None:
    """One-time: the upstream interfaces of the routers in use and the idle routers. Monthly: the idle routers' circuits."""
    result = totals(SEEDED)

    assert result.not_carried_one_time == pytest.approx(11000 + 48000)
    assert [(router.circuit_id, router.monthly_cost) for router in result.unused_routers] == [
        ("ZAYO-DAL-TR-1001", 3000),
        ("COG-NYC-TR-1001", 3000),
        ("LUMEN-DAL-TR-2001", 3000),
        ("LUMEN-NYC-TR-2001", 3000),
    ]
    assert result.not_carried_monthly == pytest.approx(12000)
    # Every circuit on a router in use is spread in full over the services through it.
    carried = shares(cost_lines(SEEDED)).circuit
    assert carried + result.not_carried_monthly == pytest.approx(sum(cost for _, cost in CIRCUITS.values()))


def test_every_line_names_how_its_cost_is_spread() -> None:
    lines = cost_lines(SEEDED)

    assert {line.method for line in lines if line.unit == ONE_TIME} == {"per active interface"}
    assert {line.method for line in lines if line.unit == PER_MONTH} == {"by bandwidth"}


def test_each_service_sum_is_rounded_once() -> None:
    lines = cost_lines(SEEDED)
    found = {service.identifier: service for service in services(SEEDED)}
    costs = {identifier: shares(service_lines(lines, identifier)) for identifier in found}

    assert len(costs) == 12
    assert (costs["DI-1001"].hardware, costs["DI-1001"].circuit) == (6400.0, 3816.79)
    assert (len(found["DI-1001"].paths), len(found["DI-2001"].paths)) == (2, 1)
    assert round(sum(cost.circuit for cost in costs.values()), 2) == pytest.approx(9000.0, abs=0.02)


# Without the circuit schema


def test_without_the_circuit_schema_the_figures_are_the_hardware_figures_only() -> None:
    without = stored_only(SEEDED)
    lines = cost_lines(without)

    assert not has_circuits(without)
    assert has_circuits(SEEDED)
    assert lines == [line for line in cost_lines(SEEDED) if line.unit == ONE_TIME]
    assert (shares(lines).hardware, shares(lines).circuit) == (61000.0, 0.0)
    assert [item.kind for item in inputs(without)] == ["Device type", "Device type"]
    result = totals(without)
    assert result.not_carried_one_time == pytest.approx(59000)
    assert result.not_carried_monthly == 0
    assert all(not router.circuit_id for router in result.unused_routers)


def test_the_csv_has_no_circuit_rows_without_the_circuit_schema() -> None:
    rows = list(csv.reader(io.StringIO(to_csv(cost_lines(stored_only(SEEDED))))))

    assert tuple(rows[0]) == CSV_HEADER
    assert len(rows) == 1 + 2 * 15
    assert not [row for row in rows[1:] if row[4] == "circuit" or row[10] == PER_MONTH]


def test_with_circuits_adds_the_circuit_query_result_or_nothing() -> None:
    stored = stored_only(SEEDED)

    assert with_circuits(stored, None) == stored
    assert traced(with_circuits(stored, build_circuit_data())) == SEEDED


def test_a_circuit_endpoint_on_no_upstream_interface_is_not_an_edge_router_circuit() -> None:
    """A circuit that lands on no edge router adds no line, such as one of data/09_circuit.yml if an operator loads it."""
    extra = build_circuit_data({"rb09-par01": ("COLT-PAR-001", 900)})["DcimCircuitEndpoint"]["edges"]
    data = {**SEEDED, "DcimCircuitEndpoint": {"edges": [*SEEDED["DcimCircuitEndpoint"]["edges"], *extra]}}

    assert cost_lines(data) == cost_lines(SEEDED)
    assert "COLT-PAR-001" not in [item.name for item in inputs(data)]


# Inputs and CSV


def test_inputs_list_each_value_as_a_demo_input_with_its_file() -> None:
    assert [(item.kind, item.name, item.value, item.label, item.source) for item in inputs(SEEDED)] == [
        ("Device type", "Generic router", 12000, "demo input", "data/06_device_type.yml"),
        ("Device type", "Generic switch", 6000, "demo input", "data/06_device_type.yml"),
        *[
            ("Circuit", circuit_id, cost, "demo input", "data/business_impact/upstream_circuits.yml")
            for circuit_id, cost in sorted(CIRCUITS.values())
        ],
    ]


def test_csv_header_and_row_order() -> None:
    lines = cost_lines(SEEDED)
    rows = list(csv.reader(io.StringIO(to_csv(lines))))

    assert tuple(rows[0]) == CSV_HEADER
    assert rows[1] == [
        "DI-1001",
        "Northbank",
        "Gold",
        "primary (sw01-par01 / rb01-par01)",
        "switch",
        "sw01-par01",
        "6000",
        "5",
        "per active interface",
        "1200.00",
        "EUR one-time",
        "",
    ]
    assert rows[3][4:11] == ["circuit", "COG-PAR-TR-1001", "2500", "13100", "by bandwidth", "1908.40", "EUR per month"]
    keys = [
        (row[0], not row[3].startswith("primary"), ("switch", "router", "circuit").index(row[4])) for row in rows[1:]
    ]
    assert keys == sorted(keys)
    assert len(rows) - 1 == 3 * 15


@pytest.mark.parametrize("note", [NO_LIST_PRICE, NO_CIRCUIT])
def test_csv_writes_an_empty_share_with_the_note(note: str) -> None:
    line = CostLine("DI-9", "C", "Gold", "primary (a / b)", "switch", "a", None, 3, None, ONE_TIME, note)

    assert to_csv([line]).splitlines()[1] == (
        f"DI-9,C,Gold,primary (a / b),switch,a,,3,per active interface,,EUR one-time,{note}"
    )


# The transform


# The stored query result alone, as Infrahub hands it to the transform.
STORED = stored_only(SEEDED)


class FakeSchema:
    def __init__(self, kinds: list[str]) -> None:
        self.kinds = kinds
        self.lookups: list[str] = []

    async def get(self, kind: str, branch: str) -> object:
        assert branch == "main"
        self.lookups.append(kind)
        if kind not in self.kinds:
            raise SchemaNotFoundError(identifier=kind)
        return object()


class FakeClient(TraversalClient):
    """The transform's client: a schema with or without the circuit endpoint kind, the circuit query, and the
    path traversal answered from the seed."""

    def __init__(self, *, circuit_schema: bool) -> None:
        super().__init__({"main": SEEDED})
        self.schema = FakeSchema(["DcimDevice", *(["DcimCircuitEndpoint"] if circuit_schema else [])])
        self.queries: list[str] = []

    def clone(self, **_: object) -> FakeClient:
        return self

    async def execute_graphql(self, query: str, branch_name: str) -> dict[str, Any]:
        assert branch_name == "main"
        self.queries.append(query)
        return build_circuit_data()


def _transform(client: FakeClient) -> CostOfService:
    return CostOfService(client=cast("InfrahubClient", client), infrahub_node=InfrahubNode, branch="main")


def test_the_transform_merges_the_circuits_when_the_circuit_schema_is_loaded() -> None:
    client = FakeClient(circuit_schema=True)
    transform = _transform(client)

    assert transform.query == "cost_of_service"
    assert asyncio.run(transform.transform(STORED)) == to_csv(cost_lines(SEEDED))
    assert client.schema.lookups == ["DcimCircuitEndpoint"]
    assert len(client.queries) == 1
    assert "query cost_of_service_circuits" in client.queries[0]


def test_the_transform_writes_no_circuit_rows_without_the_circuit_schema() -> None:
    client = FakeClient(circuit_schema=False)
    content = asyncio.run(_transform(client).transform(STORED))

    assert not client.queries
    assert content == to_csv(cost_lines(STORED))
    rows = list(csv.reader(io.StringIO(content)))
    assert {row[4] for row in rows[1:]} == {"switch", "router"}
    assert {row[10] for row in rows[1:]} == {ONE_TIME}


def test_worker_imports_the_cost_module_from_the_commit_worktree(commit_worktree: Path) -> None:
    """Infrahub imports `commits.<sha>.transforms.cost_of_service` with only the repository directory on sys.path."""
    worktree = commit_worktree
    package = f"commits.{worktree.name}"
    shutil.copytree(REPO_ROOT / "transforms", worktree / "transforms", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(
        REPO_ROOT / "service_catalog" / "cost_of_service",
        worktree / "service_catalog" / "cost_of_service",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    # The cost transform needs the cost package, the circuit query, `network.py`, and the footprint
    # module with the protocols it filters the path traversal by.
    shutil.copytree(
        REPO_ROOT / "service_catalog" / "queries",
        worktree / "service_catalog" / "queries",
    )
    (worktree / "service_catalog" / "business_impact").mkdir()
    for name in ("business_impact/__init__.py", "business_impact/footprint.py", "network.py", "protocols_async.py"):
        shutil.copy(REPO_ROOT / "service_catalog" / name, worktree / "service_catalog" / name)
    module = importlib.import_module(f"{package}.transforms.cost_of_service")
    for name in (module.COST_MODULE, module.NETWORK_MODULE):
        loaded = module.load(name)
        assert loaded.__name__ == f"{package}.{name}"
        assert loaded.__file__.startswith(str(worktree))
    assert module.load(module.CIRCUITS_MODULE).QUERY_FILE.is_relative_to(worktree)
    transform = module.CostOfService(
        client=cast("InfrahubClient", FakeClient(circuit_schema=True)), infrahub_node=InfrahubNode, branch="main"
    )
    assert asyncio.run(transform.transform(STORED)) == to_csv(cost_lines(SEEDED))
