"""Unit tests for the Planned maintenance figures, on the seed-shaped query results of `builders.py`."""

import ast
from collections.abc import Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from service_catalog.business_impact import blast_radius
from service_catalog.business_impact.blast_radius import (
    STATUS_AT_RISK,
    STATUS_DOWN,
    BlastRadius,
    build_blast_radius,
    default_picker_index,
    headline_caption,
    paths,
    picker_entries,
    service_status,
)

from .builders import (
    ALLOWED_CAPTION,
    FORBIDDEN_COPY,
    MONEY_WORDS,
    REPO_ROOT,
    SEED,
    Q1Data,
    SeedRow,
    build_q1,
    build_seeded_q1,
    service_row,
    tiles,
)


@pytest.fixture
def current_network() -> dict[str, Any]:
    return build_q1()


@pytest.fixture
def paris() -> dict[str, Any]:
    return build_q1({"rb01-par01": "maintenance"})


@pytest.fixture
def brussels() -> dict[str, Any]:
    return build_q1({"sw01-bru01": "maintenance"})


def _statuses(result: BlastRadius) -> dict[str, tuple[int, int, str]]:
    return {row.service: (row.paths_on_main, row.paths_during_change, row.status) for row in result.affected_rows}


@pytest.fixture
def seeded_network() -> dict[str, Any]:
    """The current network after `invoke seed`: the Paris Gold services have two paths."""
    return build_seeded_q1()


@pytest.fixture
def seeded_paris() -> dict[str, Any]:
    return build_seeded_q1({"rb01-par01": "maintenance"})


# Paths


def _names(data: Mapping[str, object], identifier: str) -> list[tuple[str, str]]:
    return [(path.switch.name, path.edge_router.name) for path in paths(service_row(data, identifier))]


def test_paths_pair_each_switch_with_the_edge_router_of_the_same_index(seeded_network: Q1Data) -> None:
    assert _names(seeded_network, "DI-1001") == [("sw01-par01", "rb01-par01"), ("sw02-par01", "rb02-par01")]
    assert _names(seeded_network, "DI-1003") == [("sw01-par01", "rb01-par01"), ("sw02-par01", "rb02-par01")]
    assert _names(seeded_network, "DI-2001") == [("sw01-bru01", "rb01-bru01")]


def test_paths_need_the_same_index() -> None:
    """A switch 1 and an edge router 2 are no path: the generator pairs switch N with edge router N."""
    row = SeedRow("DI-1001", "Northbank", "Gold", "1000", "sw01-par01", "rb02-par01")

    assert _names(build_q1(rows=(row,)), "DI-1001") == []


def test_paths_need_the_same_site() -> None:
    """A Paris switch 1 and a Brussels edge router 1 are no path, though their index is the same."""
    row = SeedRow("DI-1001", "Northbank", "Gold", "1000", "sw01-par01", "rb01-bru01")

    assert _names(build_q1(rows=(row,)), "DI-1001") == []


def test_paths_count_a_device_once_however_many_interfaces_sit_on_it() -> None:
    data = build_q1(rows=SEED[:1], second_paths={"DI-1001": ("sw01-par01", "rb01-par01")})

    assert _names(data, "DI-1001") == [("sw01-par01", "rb01-par01")]


@pytest.mark.parametrize(
    ("on_main", "during", "status"),
    [(2, 1, STATUS_AT_RISK), (1, 0, STATUS_DOWN), (2, 0, STATUS_DOWN), (2, 2, None), (1, 1, None), (1, 2, None)],
)
def test_service_status(on_main: int, during: int, status: str | None, current_network: Q1Data) -> None:
    service = service_row(current_network, "DI-1001")

    assert service_status(service, on_main, during) == status


def test_service_status_without_any_path_is_down_only_behind_a_device_out_of_service(paris: Q1Data) -> None:
    assert service_status(service_row(paris, "DI-1001"), 0, 0) == STATUS_DOWN
    assert service_status(service_row(paris, "DI-1003"), 0, 0) is None


# Seed figures


def test_paris_router_1_maintenance_on_the_seeded_network(seeded_paris: Q1Data, seeded_network: Q1Data) -> None:
    """The Paris Gold services keep their second path; the Silver and Bronze services behind the router go down."""
    result = build_blast_radius(seeded_paris, seeded_network)

    assert result.headline == (
        "3 Gold services for Helix Health and Northbank have fewer separate paths during this change"
    )
    assert tiles(result) == {"Customers affected": "4", "Gold services at risk": "3", "Services down": "2"}
    assert _statuses(result) == {
        "DI-1001": (2, 1, STATUS_AT_RISK),
        "DI-1002": (2, 1, STATUS_AT_RISK),
        "DI-1003": (2, 1, STATUS_AT_RISK),
        "DI-1004": (1, 0, STATUS_DOWN),
        "DI-1006": (1, 0, STATUS_DOWN),
    }
    assert result.gold_headline


def test_gold_service_with_two_paths_and_one_device_out_is_at_risk(seeded_network: Q1Data) -> None:
    data = build_seeded_q1({"sw02-par01": "maintenance"})

    rows = {row.service: row for row in build_blast_radius(data, seeded_network).affected_rows}

    assert (rows["DI-1003"].paths_on_main, rows["DI-1003"].paths_during_change) == (2, 1)
    assert rows["DI-1003"].status == STATUS_AT_RISK
    assert rows["DI-1003"].rule == 1
    assert rows["DI-1003"].switch == "Paris switch 1, Paris switch 2"
    assert rows["DI-1005"].status == STATUS_DOWN


def test_both_paris_routers_take_every_paris_service_down(seeded_network: Q1Data) -> None:
    data = build_seeded_q1({"rb01-par01": "maintenance", "rb02-par01": "maintenance"})

    result = build_blast_radius(data, seeded_network)

    assert result.headline == "3 Gold services for Helix Health and Northbank have no path during this change"
    assert tiles(result) == {"Customers affected": "4", "Gold services at risk": "0", "Services down": "7"}


def test_paris_router_1_maintenance_with_one_path(paris: Q1Data, current_network: Q1Data) -> None:
    result = build_blast_radius(paris, current_network)

    assert result.headline == "2 Gold services for Northbank have no path during this change"
    assert tiles(result) == {"Customers affected": "3", "Gold services at risk": "0", "Services down": "4"}


def test_brussels_switch_1_maintenance(brussels: Q1Data, current_network: Q1Data) -> None:
    result = build_blast_radius(brussels, current_network)

    assert result.headline == "1 Gold service for Helix Health has no path during this change"
    assert tiles(result) == {"Customers affected": "3", "Gold services at risk": "0", "Services down": "3"}
    assert _statuses(result)["DI-2001"] == (1, 0, STATUS_DOWN)


def test_current_network(current_network: Q1Data) -> None:
    result = build_blast_radius(current_network, current_network)

    assert result.headline == "No service is affected"
    assert tiles(result) == {"Customers affected": "0", "Gold services at risk": "0", "Services down": "0"}
    assert result.affected_rows == ()


def test_affected_services_rows_use_friendly_device_names(paris: Q1Data, current_network: Q1Data) -> None:
    rows = build_blast_radius(paris, current_network).affected_rows

    assert [row.service for row in rows] == ["DI-1001", "DI-1002", "DI-1004", "DI-1006"]
    first = rows[0]
    assert first.customer == "Northbank"
    assert first.tier == "Gold"
    assert first.bandwidth == "10,000 Mbps"
    assert first.switch == "Paris switch 1"
    assert first.edge_router == "Paris edge router 1"
    assert (first.paths_on_main, first.paths_during_change, first.status, first.rule) == (1, 0, STATUS_DOWN, 1)
    assert rows[2].rule == 0


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


def test_tiles_name_paths_and_no_money(seeded_paris: Q1Data, seeded_network: Q1Data) -> None:
    tiles = build_blast_radius(seeded_paris, seeded_network).tiles

    assert [tile.label for tile in tiles] == ["Customers affected", "Gold services at risk", "Services down"]
    assert all(tile.help for tile in tiles)
    assert not [text for tile in tiles for text in (tile.label, tile.value, tile.help) if MONEY_WORDS.search(text)]


# Edge cases


def _rows_with(changes: Mapping[str, Mapping[str, Any]]) -> tuple[SeedRow, ...]:
    """Return the seed rows with per-service field changes, keyed by service identifier."""
    return tuple(replace(row, **changes.get(row.identifier, {})) for row in SEED)


@pytest.mark.parametrize(
    ("drafts", "headline"),
    [
        (("DI-1003",), "2 services are affected by this change, and none of them is Gold"),
        (("DI-1003", "DI-1005"), "1 service is affected by this change, and it is not Gold"),
    ],
    ids=["plural", "singular"],
)
def test_non_gold_only_headline(drafts: tuple[str, ...], headline: str, current_network: Q1Data) -> None:
    rows = _rows_with({identifier: {"status": "draft"} for identifier in drafts})
    data = build_q1({"sw02-par01": "maintenance"}, rows=rows)

    result = build_blast_radius(data, current_network)

    assert result.headline == headline


def test_two_gold_customers_joined_with_and_in_name_order(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance", "rb02-par01": "maintenance"})

    result = build_blast_radius(data, current_network)

    assert result.headline == "3 Gold services for Helix Health and Northbank have no path during this change"


def test_empty_active_service_list_shows_no_services_found() -> None:
    rows = tuple(replace(row, status="draft") for row in SEED)
    data = build_q1(rows=rows)

    result = build_blast_radius(data, data)

    assert result.no_services
    assert result.headline == "No services were found"
    assert result.tiles == ()
    assert result.affected_rows == ()


def test_service_with_no_customer_is_unassigned(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance"}, rows=_rows_with({"DI-1004": {"customer": None}}))

    result = build_blast_radius(data, current_network)

    assert tiles(result)["Customers affected"] == "2"
    assert next(row for row in result.affected_rows if row.service == "DI-1004").customer == "Unassigned"


def test_service_with_no_tier_is_not_gold(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance"}, rows=_rows_with({"DI-1001": {"tier": None}}))

    result = build_blast_radius(data, current_network)

    assert result.headline == "1 Gold service for Northbank has no path during this change"
    row = next(row for row in result.affected_rows if row.service == "DI-1001")
    assert (row.tier, row.rule) == ("Unassigned", 0)


def test_service_new_on_the_branch_counts_its_device_pairs_as_paths_on_main() -> None:
    new = SeedRow("DI-1008", "Northbank", "Gold", "1000", "sw01-par01", "rb01-par01")
    data = build_q1({"rb01-par01": "maintenance"}, rows=(new,), second_paths={"DI-1008": ("sw02-par01", "rb02-par01")})

    result = build_blast_radius(data, build_q1(rows=()))

    assert _statuses(result) == {"DI-1008": (2, 1, STATUS_AT_RISK)}


def test_draft_services_are_excluded(paris: Q1Data, current_network: Q1Data) -> None:
    extra = (*SEED, SeedRow("DI-1008", "Northbank", "Gold", "10000", "sw01-par01", "rb01-par01", "draft"))
    data = build_q1({"rb01-par01": "maintenance"}, rows=extra)

    assert build_blast_radius(data, current_network) == build_blast_radius(paris, current_network)


@pytest.mark.parametrize("status", ["provisioning", "drained", "maintenance"])
def test_any_status_other_than_active_is_out_of_service(status: str, current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": status})

    result = build_blast_radius(data, current_network)

    assert result.headline == "2 Gold services for Northbank have no path during this change"


def test_service_behind_two_out_of_service_devices_counts_once(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance", "sw01-par01": "maintenance"})

    result = build_blast_radius(data, current_network)

    assert tiles(result)["Services down"] == "4"
    assert [row.service for row in result.affected_rows] == ["DI-1001", "DI-1002", "DI-1004", "DI-1006"]


def test_gold_headline_names_only_real_customers(current_network: Q1Data) -> None:
    data = build_q1({"rb01-par01": "maintenance"}, rows=_rows_with({"DI-1002": {"customer": None}}))

    result = build_blast_radius(data, current_network)

    assert result.headline == "2 Gold services for Northbank have no path during this change"
    assert tiles(result)["Customers affected"] == "3"


@pytest.mark.parametrize(
    ("unassigned", "headline"),
    [
        (("DI-1001", "DI-1002"), "2 Gold services have no path during this change"),
        (("DI-1001",), "1 Gold service has no path during this change"),
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


# The page and its modules write nothing to Infrahub

WRITE_HELPERS = {"create_and_save", "create_branch"}
PAGE_FILES = (
    REPO_ROOT / "service_catalog" / "views" / "3_📊_Planned_Maintenance.py",
    REPO_ROOT / "service_catalog" / "views" / "6_📍_Single_Points_of_Failure.py",
)


def _read_only_files() -> Iterator[Path]:
    package = Path(blast_radius.__file__).parent
    yield from sorted(path for path in package.glob("*.py") if path.name != "seed.py")
    yield from (path for path in PAGE_FILES if path.exists())


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


# Copy scan. It reads every string literal of the business impact pages and of the modules whose strings they
# show, and of the Gold outage guard, whose messages appear in the proposed change's check results. A forbidden
# word fails the test even on a code path the AppTest copy tests do not render. Docstrings are not scanned: they
# never reach the screen.

PACKAGE = Path(blast_radius.__file__).parent
# The home page carries the cards that link to these pages, so its copy follows the same rules.
HOME_FILE = REPO_ROOT / "service_catalog" / "🏠_Home_Page.py"
CHECK_FILE = REPO_ROOT / "checks" / "gold_outage_guard.py"
NOTIFICATION_PAGE = REPO_ROOT / "service_catalog" / "views" / "4_📣_Customer_Notification.py"
COPY_FILES = (
    *PAGE_FILES,
    NOTIFICATION_PAGE,
    HOME_FILE,
    PACKAGE / "page_views.py",
    PACKAGE / "blast_radius.py",
    PACKAGE / "single_points.py",
    PACKAGE / "notification_view.py",
    PACKAGE / "gold_outage_guard.py",
    CHECK_FILE,
)


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
    found = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and FORBIDDEN_COPY.search(node.value.replace(ALLOWED_CAPTION, ""))
    ]
    return [f"line {line}: {text!r}" for line, text in sorted(found)]


def test_copy_files_exist() -> None:
    assert [path for path in COPY_FILES if not path.exists()] == []


def test_string_literals_use_no_forbidden_word() -> None:
    problems = {path.name: found for path in COPY_FILES if (found := _forbidden_literals(path))}

    assert not problems, f"forbidden on-screen words in string literals: {problems}"


def test_page_no_longer_carries_the_counted_and_your_input_caption() -> None:
    """The sidebar caption with "Counted", "Your input" and "Not calculated" is gone with the money figures."""
    for path in (*PAGE_FILES, PACKAGE / "page_views.py"):
        page = path.read_text(encoding="utf-8")

        assert page.count(ALLOWED_CAPTION) == 0
        assert "Your input" not in page


def test_copy_scan_detects_forbidden_words(tmp_path: Path) -> None:
    source = tmp_path / "copy.py"
    source.write_text(
        '"""A branch in a docstring is fine."""\n'
        'A = "Revenue loss"\n'
        'B = f"{n} hours saved"\n'
        'C = "Pick a branch"\n'
        f'D = "{ALLOWED_CAPTION}"\n'
        'E = "source_branch"\n',
        encoding="utf-8",
    )

    assert _forbidden_literals(source) == [
        "line 2: 'Revenue loss'",
        "line 3: ' hours saved'",
        "line 4: 'Pick a branch'",
    ]


def test_the_tier_names_match_the_tiers_in_the_data() -> None:
    """The list order and the Gold-only behavior follow these names, so a tier renamed or added in the data fails here."""
    documents = yaml.safe_load_all((REPO_ROOT / "data" / "10_customers_tiers.yml").read_text())
    tiers = [
        item["name"]
        for document in documents
        if document["spec"]["kind"] == "ServiceTier"
        for item in document["spec"]["data"]
    ]

    assert tuple(tiers) == blast_radius.TIER_ORDER
    assert blast_radius.GOLD in tiers
