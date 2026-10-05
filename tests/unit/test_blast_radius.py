"""Unit tests for the Blast radius figures.

The fixture builds `data` dicts in the shape of the stored query
`business_impact_services` for the twelve seed services and sixteen
devices that `invoke seed` creates. Each service has two dedicated interfaces,
as the generator builds them: a customer port on the pinned switch (role
`core`) and a gateway interface on the edge router with the same index
(role `edge`). Only the eight par01 and bru01 devices carry a description,
as in `data/08_device.yml`.
"""

import ast
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from service_catalog.business_impact import blast_radius
from service_catalog.business_impact.blast_radius import (
    BlastRadius,
    build_blast_radius,
    chart_segments,
    default_picker_index,
    format_eur,
    headline_caption,
    picker_entries,
)

Q1Data = dict[str, Any]

REPO_ROOT = Path(__file__).resolve().parents[2]

TIER_CREDIT = {"Gold": 25, "Silver": 10, "Bronze": 5}

DESCRIPTIONS = {
    "rb01-par01": "Paris edge router 1",
    "rb02-par01": "Paris edge router 2",
    "rb01-bru01": "Brussels edge router 1",
    "rb02-bru01": "Brussels edge router 2",
    "sw01-par01": "Paris switch 1",
    "sw02-par01": "Paris switch 2",
    "sw01-bru01": "Brussels switch 1",
    "sw02-bru01": "Brussels switch 2",
}

SITES = ("bru01", "par01", "nyc01", "dal01")
SITE_NAMES = {"bru01": "Brussels", "par01": "Paris", "nyc01": "New York", "dal01": "Dallas"}


@dataclass(frozen=True)
class SeedRow:
    identifier: str
    customer: str | None
    tier: str | None
    bandwidth: str
    switch: str
    router: str
    charge: int | None
    status: str = "active"


SEED = (
    SeedRow("DI-1001", "Northbank", "Gold", "10000", "sw01-par01", "rb01-par01", 8100),
    SeedRow("DI-1002", "Northbank", "Gold", "1000", "sw01-par01", "rb01-par01", 2160),
    SeedRow("DI-1003", "Helix Health", "Gold", "1000", "sw02-par01", "rb02-par01", 2160),
    SeedRow("DI-1004", "Maison Verte", "Silver", "1000", "sw01-par01", "rb01-par01", 1560),
    SeedRow("DI-1005", "Maison Verte", "Silver", "100", "sw02-par01", "rb02-par01", 520),
    SeedRow("DI-1006", "Rapid Freight", "Bronze", "100", "sw01-par01", "rb01-par01", 400),
    SeedRow("DI-1007", "Rapid Freight", "Bronze", "1000", "sw02-par01", "rb02-par01", 1200),
    SeedRow("DI-2001", "Helix Health", "Gold", "10000", "sw01-bru01", "rb01-bru01", 8100),
    SeedRow("DI-2002", "Northbank", "Gold", "1000", "sw02-bru01", "rb02-bru01", 2160),
    SeedRow("DI-2003", "Maison Verte", "Silver", "1000", "sw01-bru01", "rb01-bru01", 1560),
    SeedRow("DI-2004", "Rapid Freight", "Bronze", "100", "sw02-bru01", "rb02-bru01", 400),
    SeedRow("DI-2005", "Rapid Freight", "Bronze", "1000", "sw01-bru01", "rb01-bru01", 1200),
)


def _value(value: object) -> dict[str, object]:
    return {"value": value}


def _device_names() -> list[str]:
    return [f"{prefix}0{index}-{site}" for site in SITES for prefix in ("sw", "rb") for index in (1, 2)]


def _device_node(name: str, status: str) -> dict[str, object]:
    return {
        "name": _value(name),
        "description": _value(DESCRIPTIONS.get(name)),
        "role": _value("core" if name.startswith("sw") else "edge"),
        "status": _value(status),
    }


def _interface(name: str, device: dict[str, object]) -> dict[str, object]:
    return {"node": {"name": _value(name), "device": {"node": device}}}


def build_q1(
    statuses: Mapping[str, str] | None = None,
    rows: tuple[SeedRow, ...] = SEED,
    tier_credit: Mapping[str, int] = TIER_CREDIT,
    tiers: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Build query `data` with every device active unless `statuses` says otherwise.

    `tiers` fills the `ServiceTier` block (name to SLA credit percentage); it defaults to `tier_credit`.
    """
    status_of = dict.fromkeys(_device_names(), "active")
    status_of.update(statuses or {})
    switch_ports: dict[str, int] = {}
    service_edges: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        port = switch_ports.get(row.switch, 4)
        switch_ports[row.switch] = port + 1
        site = row.switch.split("-")[1]
        service_edges.append(
            {
                "node": {
                    "service_identifier": _value(row.identifier),
                    "status": _value(row.status),
                    "bandwidth": _value(row.bandwidth),
                    "monthly_charge": _value(row.charge),
                    "location": {"node": {"shortname": _value(site), "name": _value(SITE_NAMES[site])}},
                    "customer": {"node": {"name": _value(row.customer)} if row.customer else None},
                    "tier": {
                        "node": {"name": _value(row.tier), "sla_credit_pct": _value(tier_credit.get(row.tier))}
                        if row.tier
                        else None
                    },
                    "dedicated_interfaces": {
                        "edges": [
                            _interface(f"Ethernet{port}", _device_node(row.switch, status_of[row.switch])),
                            _interface(f"vlan_{1000 + index}", _device_node(row.router, status_of[row.router])),
                        ]
                    },
                }
            }
        )
    device_edges = [
        {
            "node": {
                **_device_node(name, status_of[name]),
                "location": {"node": {"shortname": _value(name.split("-")[1])}},
            }
        }
        for name in _device_names()
    ]
    tier_edges = [
        {"node": {"name": _value(name), "sla_credit_pct": _value(pct)}}
        for name, pct in (tier_credit if tiers is None else tiers).items()
    ]
    return {
        "ServiceDedicatedInternet": {"edges": service_edges},
        "DcimDevice": {"edges": device_edges},
        "ServiceTier": {"edges": tier_edges},
    }


@pytest.fixture
def current_network() -> dict[str, Any]:
    return build_q1()


@pytest.fixture
def paris() -> dict[str, Any]:
    return build_q1({"rb01-par01": "maintenance"})


@pytest.fixture
def brussels() -> dict[str, Any]:
    return build_q1({"sw01-bru01": "maintenance"})


def _tiles(result: BlastRadius) -> dict[str, str]:
    return {tile.label: tile.value for tile in result.tiles}


def _customers(result: BlastRadius) -> dict[str, tuple[int, int]]:
    return {row.customer: (row.affected_annual, row.annual) for row in result.customer_values}


def _routers(result: BlastRadius) -> list[tuple[str, str, bool]]:
    return [(row.label, format_eur(row.gold_annual), row.in_this_change) for row in result.routers]


# Seed figures


def test_paris_router_1_maintenance(paris: Q1Data, current_network: Q1Data) -> None:
    result = build_blast_radius(paris, current_network)

    assert result.headline == "2 Gold services for Northbank have no other path during this change"
    assert _tiles(result) == {
        "Customers affected": "3",
        "Gold services affected": "2 of 5",
        "Gold SLA credit exposure, per month": "€2,565",
    }
    customers = _customers(result)
    assert customers["Northbank"] == (123_120, 149_040)
    assert customers["Maison Verte"][0] == 18_720
    assert customers["Rapid Freight"][0] == 4_800
    assert customers["Helix Health"][0] == 0
    assert format_eur(customers["Northbank"][0]) == "€123,120"
    assert format_eur(customers["Northbank"][1]) == "€149,040"


def test_chart_segments_split_each_bar_into_affected_and_not_affected(paris: Q1Data, current_network: Q1Data) -> None:
    segments = chart_segments(build_blast_radius(paris, current_network).customer_values)

    assert [(row.customer, row.segment, row.annual) for row in segments] == [
        ("Helix Health", "Affected", 0),
        ("Helix Health", "Not affected", 123_120),
        ("Maison Verte", "Affected", 18_720),
        ("Maison Verte", "Not affected", 24_960),
        ("Northbank", "Affected", 123_120),
        ("Northbank", "Not affected", 25_920),
        ("Rapid Freight", "Affected", 4_800),
        ("Rapid Freight", "Not affected", 33_600),
    ]


def test_paris_full_bars_match_figure_definitions(paris: Q1Data, current_network: Q1Data) -> None:
    customers = _customers(build_blast_radius(paris, current_network))

    assert {name: annual for name, (_, annual) in customers.items()} == {
        "Northbank": 149_040,
        "Helix Health": 123_120,
        "Maison Verte": 43_680,
        "Rapid Freight": 38_400,
    }


def test_brussels_switch_1_maintenance(brussels: Q1Data, current_network: Q1Data) -> None:
    result = build_blast_radius(brussels, current_network)

    assert result.headline == "1 Gold service for Helix Health has no other path during this change"
    assert _tiles(result) == {
        "Customers affected": "3",
        "Gold services affected": "1 of 5",
        "Gold SLA credit exposure, per month": "€2,025",
    }


def test_current_network(current_network: Q1Data) -> None:
    result = build_blast_radius(current_network, current_network)

    assert result.headline == "No service is affected"
    assert _tiles(result) == {
        "Customers affected": "0",
        "Gold services affected": "0 of 5",
        "Gold SLA credit exposure, per month": "€0",
    }
    assert result.affected_rows == ()
    assert not any(row.in_this_change for row in result.routers)


def test_router_ranking_paris(paris: Q1Data, current_network: Q1Data) -> None:
    result = build_blast_radius(paris, current_network)

    assert _routers(result) == [
        ("Paris edge router 1", "€123,120", True),
        ("Brussels edge router 1", "€97,200", False),
        ("Paris edge router 2", "€25,920", False),
        ("Brussels edge router 2", "€25,920", False),
    ]
    assert not any("nyc01" in row.label or "dal01" in row.label for row in result.routers)


def test_router_ranking_values_do_not_depend_on_the_change(brussels: Q1Data, current_network: Q1Data) -> None:
    result = build_blast_radius(brussels, current_network)

    assert [(label, value) for label, value, _ in _routers(result)] == [
        ("Paris edge router 1", "€123,120"),
        ("Brussels edge router 1", "€97,200"),
        ("Paris edge router 2", "€25,920"),
        ("Brussels edge router 2", "€25,920"),
    ]
    # Only a switch changed, so no edge router carries the marker.
    assert not any(row.in_this_change for row in result.routers)


def test_affected_services_rows_use_friendly_device_names(paris: Q1Data, current_network: Q1Data) -> None:
    rows = build_blast_radius(paris, current_network).affected_rows

    assert [row.service for row in rows] == ["DI-1001", "DI-1002", "DI-1004", "DI-1006"]
    first = rows[0]
    assert first.customer == "Northbank"
    assert first.tier == "Gold"
    assert first.bandwidth == "10,000 Mbps"
    assert first.switch == "Paris switch 1"
    assert first.edge_router == "Paris edge router 1"
    assert first.monthly_charge == "€8,100"


def test_device_label_falls_back_to_name() -> None:
    rows = tuple(
        replace(row, switch=row.switch.replace("par01", "nyc01"), router=row.router.replace("par01", "nyc01"))
        for row in SEED
        if row.identifier == "DI-1001"
    )
    data = build_q1({"rb01-nyc01": "maintenance"}, rows=rows)

    affected = build_blast_radius(data, build_q1(rows=rows)).affected_rows

    assert affected[0].switch == "sw01-nyc01"
    assert affected[0].edge_router == "rb01-nyc01"


def test_tile_help_texts(paris: Q1Data, current_network: Q1Data) -> None:
    helps = {tile.label: tile.help for tile in build_blast_radius(paris, current_network).tiles}

    assert helps["Customers affected"] == "Counted"
    assert helps["Gold services affected"] == "Counted"
    assert helps["Gold SLA credit exposure, per month"] == "Your input. Gold tier credit: 25%"


# Edge cases


def _rows_with(changes: Mapping[str, Mapping[str, Any]]) -> tuple[SeedRow, ...]:
    """Return the seed rows with per-service field changes, keyed by service identifier."""
    return tuple(replace(row, **changes.get(row.identifier, {})) for row in SEED)


def test_non_gold_only_headline_plural(current_network: Q1Data) -> None:
    data = build_q1({"sw02-par01": "maintenance"}, rows=_rows_with({"DI-1003": {"status": "draft"}}))

    result = build_blast_radius(data, current_network)

    assert result.headline == "2 services have no other path during this change, and none of them is Gold"


def test_non_gold_only_headline_singular(current_network: Q1Data) -> None:
    rows = _rows_with({"DI-1003": {"status": "draft"}, "DI-1005": {"status": "draft"}})
    data = build_q1({"sw02-par01": "maintenance"}, rows=rows)

    result = build_blast_radius(data, current_network)

    assert result.headline == "1 service has no other path during this change, and it is not Gold"


def test_two_gold_customers_joined_with_and_in_name_order(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance", "rb02-par01": "maintenance"})

    result = build_blast_radius(data, current_network)

    assert result.headline == "3 Gold services for Helix Health and Northbank have no other path during this change"


def test_empty_active_service_list_shows_no_services_found() -> None:
    rows = tuple(replace(row, status="draft") for row in SEED)
    data = build_q1(rows=rows)

    result = build_blast_radius(data, data)

    assert result.no_services
    assert result.headline == "No services were found"
    assert result.tiles == ()
    assert result.customer_values == ()
    assert result.affected_rows == ()
    assert result.routers == ()


def test_service_with_no_customer_is_unassigned(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance"}, rows=_rows_with({"DI-1004": {"customer": None}}))

    result = build_blast_radius(data, current_network)

    customers = _customers(result)
    assert customers["Unassigned"] == (18_720, 18_720)
    assert customers["Maison Verte"] == (0, 24_960)
    assert _tiles(result)["Customers affected"] == "2"
    assert next(row for row in result.affected_rows if row.service == "DI-1004").customer == "Unassigned"


def test_service_with_no_tier_is_not_gold(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance"}, rows=_rows_with({"DI-1001": {"tier": None}}))

    result = build_blast_radius(data, current_network)

    assert result.headline == "1 Gold service for Northbank has no other path during this change"
    assert _tiles(result)["Gold services affected"] == "1 of 4"
    assert _tiles(result)["Gold SLA credit exposure, per month"] == "€540"
    assert next(row for row in result.affected_rows if row.service == "DI-1001").tier == "Unassigned"


def test_service_with_no_monthly_charge_counts_zero(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance"}, rows=_rows_with({"DI-1002": {"charge": None}}))

    result = build_blast_radius(data, current_network)

    assert _customers(result)["Northbank"] == (97_200, 123_120)
    assert _tiles(result)["Gold SLA credit exposure, per month"] == "€2,025"
    assert next(row for row in result.affected_rows if row.service == "DI-1002").monthly_charge == "Not set"


def test_draft_services_are_excluded(paris: Q1Data, current_network: Q1Data) -> None:
    extra = (*SEED, SeedRow("DI-1008", "Northbank", "Gold", "10000", "sw01-par01", "rb01-par01", 8100, "draft"))
    data = build_q1({"rb01-par01": "maintenance"}, rows=extra)

    assert build_blast_radius(data, current_network) == build_blast_radius(paris, current_network)


@pytest.mark.parametrize("status", ["provisioning", "drained", "maintenance"])
def test_any_status_other_than_active_is_out_of_service(status: str, current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": status})

    result = build_blast_radius(data, current_network)

    assert result.headline == "2 Gold services for Northbank have no other path during this change"


def test_service_behind_two_out_of_service_devices_counts_once(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance", "sw01-par01": "maintenance"})

    result = build_blast_radius(data, current_network)

    assert _tiles(result)["Gold services affected"] == "2 of 5"
    assert _tiles(result)["Gold SLA credit exposure, per month"] == "€2,565"
    assert [row.service for row in result.affected_rows] == ["DI-1001", "DI-1002", "DI-1004", "DI-1006"]


def test_gold_credit_percentage_comes_from_the_gold_tier() -> None:
    credit = {**TIER_CREDIT, "Gold": 30}
    data = build_q1({"rb01-par01": "maintenance"}, tier_credit=credit)

    result = build_blast_radius(data, build_q1(tier_credit=credit))

    tile = next(tile for tile in result.tiles if tile.label == "Gold SLA credit exposure, per month")
    assert tile.help == "Your input. Gold tier credit: 30%"
    assert tile.value == "€3,078"


def test_gold_credit_percentage_is_read_from_the_gold_tier_node(current_network: Q1Data) -> None:
    """The help text reads the Gold tier node, not the first Gold service."""
    data = build_q1({"rb01-par01": "maintenance"}, tiers={**TIER_CREDIT, "Gold": 40})

    result = build_blast_radius(data, current_network)

    tile = next(tile for tile in result.tiles if tile.label == "Gold SLA credit exposure, per month")
    assert tile.help == "Your input. Gold tier credit: 40%"


def test_gold_credit_percentage_not_set_without_a_gold_tier_node(current_network: Q1Data) -> None:
    tiers = {name: pct for name, pct in TIER_CREDIT.items() if name != "Gold"}
    data = build_q1({"rb01-par01": "maintenance"}, tiers=tiers)

    result = build_blast_radius(data, current_network)

    tile = next(tile for tile in result.tiles if tile.label == "Gold SLA credit exposure, per month")
    assert tile.help == "Your input. Gold tier credit: Not set"


def test_gold_headline_names_only_real_customers(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance"}, rows=_rows_with({"DI-1002": {"customer": None}}))

    result = build_blast_radius(data, current_network)

    assert result.headline == "2 Gold services for Northbank have no other path during this change"
    assert _tiles(result)["Customers affected"] == "3"


@pytest.mark.parametrize(
    ("unassigned", "headline"),
    [
        (("DI-1001", "DI-1002"), "2 Gold services have no other path during this change"),
        (("DI-1001",), "1 Gold service has no other path during this change"),
    ],
)
def test_gold_headline_without_names_when_every_gold_service_is_unassigned(
    unassigned: tuple[str, ...], headline: str, current_network: Q1Data
) -> None:
    changes: dict[str, dict[str, Any]] = {identifier: {"customer": None} for identifier in unassigned}
    if len(unassigned) == 1:
        changes["DI-1002"] = {"tier": "Silver"}
    data = build_q1({"rb01-par01": "maintenance"}, rows=_rows_with(changes))

    result = build_blast_radius(data, current_network)

    assert result.headline == headline
    assert "Unassigned" not in result.headline


def test_headline_caption_for_proposed_changes(paris: Q1Data, current_network: Q1Data) -> None:
    gold = build_blast_radius(paris, current_network)
    data = build_q1({"sw02-par01": "maintenance"}, rows=_rows_with({"DI-1003": {"status": "draft"}}))
    other = build_blast_radius(data, current_network)

    assert headline_caption("Paris router 1 maintenance", gold) == (
        "Paris router 1 maintenance · found in a proposed change, before merge"
    )
    assert headline_caption("Paris switch 2 maintenance", other) == (
        "Paris switch 2 maintenance · seen in a proposed change, before merge"
    )


def test_headline_caption_is_empty_for_current_network(current_network: Q1Data) -> None:
    result = build_blast_radius(current_network, current_network)

    assert not headline_caption("Current network", result)


PROPOSED_CHANGES: list[dict[str, Any]] = [
    {"name": "Implement service DI-3001", "source_branch": "order-di-3001", "tags": ["service_request"]},
    {"name": "Paris router 1 maintenance", "source_branch": "maint-rb01-par01", "tags": []},
    {"name": "Brussels switch 1 maintenance", "source_branch": "maint-sw01-bru01", "tags": []},
]


def test_picker_entries_order_and_filter() -> None:
    entries = picker_entries(PROPOSED_CHANGES)

    assert [(entry.label, entry.branch) for entry in entries] == [
        ("Current network", "main"),
        ("Brussels switch 1 maintenance", "maint-sw01-bru01"),
        ("Paris router 1 maintenance", "maint-rb01-par01"),
    ]


def test_picker_defaults_to_paris_router_1_maintenance() -> None:
    entries = picker_entries(PROPOSED_CHANGES)

    assert entries[default_picker_index(entries)].label == "Paris router 1 maintenance"


def test_picker_defaults_to_current_network_without_paris() -> None:
    entries = picker_entries([change for change in PROPOSED_CHANGES if not change["name"].startswith("Paris")])

    assert default_picker_index(entries) == 0
    assert entries[0].label == "Current network"


def test_format_eur() -> None:
    assert format_eur(0) == "€0"
    assert format_eur(2565) == "€2,565"
    assert format_eur(123_120) == "€123,120"
    assert format_eur(540.5) == "€541"


# The page and its modules write nothing to Infrahub

WRITE_HELPERS = {"create_and_save", "create_branch"}
PAGE_FILE = REPO_ROOT / "service_catalog" / "pages" / "3_📊_Business_Impact.py"


def _read_only_files() -> Iterator[Path]:
    package = Path(blast_radius.__file__).parent
    yield from sorted(path for path in package.glob("*.py") if path.name != "seed.py")
    if PAGE_FILE.exists():
        yield PAGE_FILE


def _write_uses(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.extend(f"import {alias.name}" for alias in node.names if alias.name in WRITE_HELPERS)
        elif isinstance(node, ast.Name) and node.id in WRITE_HELPERS:
            found.append(f"name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in WRITE_HELPERS:
            found.append(f"attribute {node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "save":
            found.append(f"call .save( on line {node.lineno}")
    return found


def test_page_and_modules_write_nothing() -> None:
    files = list(_read_only_files())
    assert files, "expected at least blast_radius.py to be scanned"
    problems = {
        str(path.relative_to(REPO_ROOT)): uses
        for path in files
        if (uses := _write_uses(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert not problems, f"write calls found in read-only Business Impact code: {problems}"


def test_write_scan_detects_writes() -> None:
    source = "from service_catalog.infrahub import create_and_save\nnode.save(allow_upsert=True)\n"

    assert _write_uses(ast.parse(source)) == ["import create_and_save", "call .save( on line 2"]


# Copy scan. It reads every string literal in the
# page, in service_catalog/business_impact/*.py and in checks/gold_outage_guard.py, so a forbidden word fails the test even on a code path the
# AppTest copy test in test_business_impact_page.py does not render. Docstrings are not scanned: they never
# reach the screen.

FORBIDDEN_COPY = re.compile(
    r"branch|\bROI\b|\bsavings?\b|\bhours?\b|time saved|outage cost|cost of an outage|\bloss\b|at risk|\bchurn\b",
    re.IGNORECASE,
)
ALLOWED_CAPTION = "Not calculated: outage cost, time saved, ROI, churn."

# Literals that never reach the page, as (file name, literal). Each one is named here so a new one fails the test.
NOT_ON_SCREEN = {
    # GraphQL field name of CoreProposedChange, used as a dict key.
    ("3_📊_Business_Impact.py", "source_branch"),
    ("blast_radius.py", "source_branch"),
    # `invoke seed` prints these in the terminal; the page never imports seed.py.
    ("seed.py", " --branch "),
    ("seed.py", ") on branch "),
}


def _docstrings(tree: ast.AST) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, owners)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }


def _forbidden_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstrings(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or id(node) in docstrings:
            continue
        if (path.name, node.value) in NOT_ON_SCREEN:
            continue
        if FORBIDDEN_COPY.search(node.value.replace(ALLOWED_CAPTION, "")):
            found.append((node.lineno, node.value))
    return [f"line {line}: {text!r}" for line, text in sorted(found)]


HOME_FILE = REPO_ROOT / "service_catalog" / "🏠_Home_Page.py"
# The Gold outage guard logs its messages to the proposed change's check results, so its copy follows the same rules.
CHECK_FILE = REPO_ROOT / "checks" / "gold_outage_guard.py"


def test_copy_scan_covers_the_page_and_every_module() -> None:
    names = {path.name for path in _copy_files()}

    assert {
        "3_📊_Business_Impact.py",
        "🏠_Home_Page.py",
        "blast_radius.py",
        "gold_outage_guard.py",
        "seed.py",
    } <= names
    assert CHECK_FILE in _copy_files()


def _copy_files() -> list[Path]:
    package = Path(blast_radius.__file__).parent
    # The home page carries the card that links to the Business Impact page, so its copy follows the same rules.
    return [*sorted(package.glob("*.py")), PAGE_FILE, HOME_FILE, CHECK_FILE]


def test_string_literals_use_no_forbidden_word() -> None:
    problems = {path.name: found for path in _copy_files() if (found := _forbidden_literals(path))}

    assert not problems, f"forbidden on-screen words in string literals: {problems}"


def test_sidebar_caption_is_the_only_allowed_occurrence() -> None:
    page = PAGE_FILE.read_text(encoding="utf-8")

    assert page.count(ALLOWED_CAPTION) == 1


def test_copy_scan_detects_forbidden_words(tmp_path: Path) -> None:
    source = tmp_path / "copy.py"
    source.write_text(
        '"""A branch in a docstring is fine."""\n'
        'A = "Revenue at risk"\n'
        'B = f"{n} hours saved"\n'
        'C = "Pick a branch"\n'
        f'D = "{ALLOWED_CAPTION}"\n',
        encoding="utf-8",
    )

    assert _forbidden_literals(source) == [
        "line 2: 'Revenue at risk'",
        "line 3: ' hours saved'",
        "line 4: 'Pick a branch'",
    ]
