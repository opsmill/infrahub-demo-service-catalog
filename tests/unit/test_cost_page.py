"""Unit tests of the Cost of Service page: its texts, tables and chart, and a smoke run.

The labels, texts, rows and chart live in `cost_of_service/view.py` and are tested as plain
functions. The smoke run uses Streamlit's AppTest with the Infrahub reads replaced: the query
result is the seed-shaped fixture of `builders.py`, and the artifact content is the CSV the
cost transform returns for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from streamlit.testing.v1 import AppTest

from service_catalog.artifact_view import REGENERATE, STALE
from service_catalog.cost_of_service.circuits import read_circuits
from service_catalog.cost_of_service.cost import (
    CostLine,
    cost_lines,
    number_text,
    service_lines,
    services,
    to_csv,
    totals,
)
from service_catalog.cost_of_service.view import (
    ARTIFACT_NAME,
    CAPEX,
    NOT_GENERATED,
    OPEX,
    OPEX_NEEDS_CIRCUITS,
    PAGE_CAPTION,
    SEGMENT_COLORS,
    UNITS,
    Unit,
    axis_ticks,
    bar_order,
    calculation,
    categories,
    category,
    composition_chart,
    composition_rows,
    csv_is_current,
    left_out_text,
    not_carried_text,
    path_rows,
    service_rows,
    worked_example,
)
from service_catalog.infrahub import Generation

from .builders import REPO_ROOT, SEEDED, build_circuit_data, run_async_on_fixture, stored_only

if TYPE_CHECKING:
    from collections.abc import Callable

PAGE = str(REPO_ROOT / "service_catalog" / "views" / "5_💶_Cost_of_Service.py")
LINES = cost_lines(SEEDED)
FOUND = [service for service in services(SEEDED) if service.paths]
TOTALS = totals(SEEDED)
DI_1001 = next(service for service in FOUND if service.identifier == "DI-1001")


# Units and texts


def test_the_switch_offers_capex_first() -> None:
    assert UNITS == (CAPEX, OPEX)
    assert [unit.label for unit in UNITS] == ["CAPEX: hardware, one-time", "OPEX: circuits, per month"]


def test_not_carried_text_names_where_the_cost_comes_from() -> None:
    assert not_carried_text(CAPEX, TOTALS) == (
        "Not carried by any service: 59,000.00 EUR one-time, from the upstream interfaces of the edge routers "
        "in use (11,000.00) and the 4 edge routers with no service (48,000.00)."
    )
    assert not_carried_text(OPEX, TOTALS) == (
        "Not carried by any service: 12,000.00 EUR per month, the circuits of the 4 edge routers with no service."
    )


def test_left_out_text_counts_only_the_lines_of_the_unit() -> None:
    line = LINES[2]
    lines = [
        CostLine(line.service, line.customer, line.tier, line.path, "circuit", "", None, 0, None, OPEX.line_unit, note)
        for note in ("no circuit", "no circuit", "no monthly cost")
    ]

    assert left_out_text(CAPEX, LINES) is None
    assert left_out_text(CAPEX, lines) is None
    assert (
        left_out_text(OPEX, lines) == "Left out of the figures: 2 lines with no circuit, 1 line with no monthly cost."
    )


def test_path_table_shows_the_parts_of_one_unit() -> None:
    capex = path_rows(CAPEX, service_lines(LINES, "DI-1001"))
    opex = path_rows(OPEX, service_lines(LINES, "DI-1001"))

    assert [(row["Path"], row["Part"]) for row in capex] == [
        ("primary (sw01-par01 / rb01-par01)", "switch"),
        ("primary (sw01-par01 / rb01-par01)", "router"),
        ("backup (sw02-par01 / rb02-par01)", "switch"),
        ("backup (sw02-par01 / rb02-par01)", "router"),
    ]
    assert capex[0] == {
        "Path": "primary (sw01-par01 / rb01-par01)",
        "Part": "switch",
        "Item": "sw01-par01",
        "Input (EUR, one-time)": "6,000",
        "Divisor (active interfaces)": "5",
        "Share (EUR, one-time)": "1,200.00",
    }
    assert opex[1] == {
        "Path": "backup (sw02-par01 / rb02-par01)",
        "Part": "circuit",
        "Item": "COLT-PAR-TR-2001",
        "Input (EUR per month)": "2,500",
        "Divisor (Mbit/s)": "13,100",
        "Share (EUR per month)": "1,908.40",
    }


@pytest.mark.parametrize(("unit", "total"), [(CAPEX, "6,400.00"), (OPEX, "3,816.79")])
def test_service_table_has_one_row_per_service_in_one_unit(unit: Unit, total: str) -> None:
    rows = service_rows(unit, LINES, FOUND)

    assert len(rows) == 12
    assert rows[0] == {
        "Service": "DI-1001",
        "Customer": "Northbank",
        "Tier": "Gold",
        "Bandwidth (Mbit/s)": "10,000",
        "Paths": 2,
        f"Total ({unit.amount_unit})": total,
    }


def test_worked_example_gives_each_number_of_di_1001_in_one_unit() -> None:
    capex = worked_example(CAPEX, LINES, DI_1001)
    opex = worked_example(OPEX, LINES, DI_1001)

    assert "DI-1001 (Northbank, Gold), 10,000 Mbit/s" in capex
    assert "switch sw01-par01: 6,000 EUR / 5 active interfaces = 1,200.00 EUR" in capex
    assert "Together: 6,400.00 EUR, one-time." in capex
    assert "circuit" not in capex
    assert (
        "circuit COG-PAR-TR-1001: 2,500 EUR per month x 10,000 Mbit/s / 13,100 Mbit/s through its edge router "
        "= 1,908.40 EUR per month"
    ) in opex
    assert "Together: 3,816.79 EUR per month." in opex
    assert "active interfaces" not in opex


# The composition chart


def test_each_part_kind_maps_to_one_category() -> None:
    assert [category(part) for part in ("switch", "router", "circuit")] == [
        "Switching",
        "Routing",
        "Upstream circuits",
    ]
    assert categories(CAPEX, LINES) == ["Switching", "Routing"]
    assert categories(OPEX, LINES) == ["Upstream circuits"]


def test_capex_composition_stacks_each_service_by_category_highest_first() -> None:
    rows, ticks = composition_rows(CAPEX, LINES, FOUND)
    bars = bar_order(rows)

    # Brussels switch 2 paths cost the most hardware; equal totals are ordered by service identifier.
    assert bars[:3] == ["DI-2002", "DI-2004", "DI-1001"]
    assert len(bars) == 12
    assert [(row["Segment"], row["Order"], row["Share"]) for row in rows if row["Bar"] == "DI-1001"] == [
        ("Switching", 0, 2400.0),
        ("Routing", 1, 4000.0),
    ]
    assert ticks == [0, 2000, 4000, 6000, 8000]
    # A one-path service has the same two categories as a two-path service.
    assert [row["Segment"] for row in rows if row["Bar"] == "DI-2001"] == ["Switching", "Routing"]


def test_opex_composition_has_one_category_per_service() -> None:
    rows, _ = composition_rows(OPEX, LINES, FOUND)

    assert bar_order(rows)[:2] == ["DI-1001", "DI-2002"]
    assert len(rows) == 12
    assert {row["Segment"] for row in rows} == {"Upstream circuits"}
    assert [row["Share"] for row in rows if row["Bar"] == "DI-1001"] == [3816.79]


def test_number_text_rounds_to_the_cent_in_each_display_style() -> None:
    values = (6000, 1200.0, 1908.396, 19.0849, 0.004, None)

    assert [number_text(value, grouped=True) for value in values] == ["6,000", "1,200", "1,908.40", "19.08", "0", ""]
    assert [number_text(value, grouped=True, cents=True) for value in values] == [
        "6,000.00",
        "1,200.00",
        "1,908.40",
        "19.08",
        "0.00",
        "",
    ]
    assert [number_text(value) for value in values] == ["6000", "1200", "1908.40", "19.08", "0", ""]
    assert number_text(1908.396, cents=True) == "1908.40"


def test_calculation_shows_the_numbers_of_one_share() -> None:
    own = service_lines(LINES, "DI-1001")
    switch = next(line for line in own if line.item == "sw01-par01")
    circuit = next(line for line in own if line.item == "COG-PAR-TR-1001")

    assert calculation(switch, DI_1001.bandwidth) == "6,000 / 5 active interfaces = 1,200"
    assert calculation(circuit, DI_1001.bandwidth) == "2,500 x 10,000 / 13,100 Mbit/s = 1,908.40"


@pytest.mark.parametrize(
    ("top", "ticks"),
    [
        (7000.0, [0, 2000, 4000, 6000, 8000]),
        (3816.79, [0, 1000, 2000, 3000, 4000]),
        (8000.0, [0, 2000, 4000, 6000, 8000]),
        (240.0, [0, 50, 100, 150, 200, 250]),
        (0.0, [0, 1]),
    ],
)
def test_axis_has_a_few_round_ticks_from_zero(top: float, ticks: list[float]) -> None:
    assert axis_ticks(top) == ticks


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_each_segment_color_has_a_text_color(theme: str) -> None:
    for color, text in SEGMENT_COLORS[theme]:
        assert color.startswith("#")
        assert text in {"#ffffff", "#1a1a1a"}


def test_each_segment_has_its_middle_its_label_and_a_tooltip_with_each_calculation() -> None:
    capex = [row for row in composition_rows(CAPEX, LINES, FOUND)[0] if row["Bar"] == "DI-1001"]
    opex = [row for row in composition_rows(OPEX, LINES, FOUND)[0] if row["Bar"] == "DI-1001"]

    assert [(row["Middle"], row["Label"]) for row in capex] == [(1200.0, "2,400"), (4400.0, "4,000")]
    assert capex[0]["Tooltip"] == {
        "Service": "DI-1001",
        "Customer": "Northbank",
        "Tier": "Gold",
        "Category": "Switching",
        "Calculation": "sw01-par01: 6,000 / 5 active interfaces = 1,200; sw02-par01: 6,000 / 5 active interfaces = 1,200",
        "Category total": "2,400 EUR, one-time",
        "Service total": "6,400 EUR, one-time",
    }
    assert opex[0]["Tooltip"] == {
        "Service": "DI-1001",
        "Customer": "Northbank",
        "Tier": "Gold",
        "Category": "Upstream circuits",
        "Calculation": (
            "COG-PAR-TR-1001: 2,500 x 10,000 / 13,100 Mbit/s = 1,908.40; "
            "COLT-PAR-TR-2001: 2,500 x 10,000 / 13,100 Mbit/s = 1,908.40"
        ),
        "Category total": "3,816.79 EUR per month",
        "Service total": "3,816.79 EUR per month",
    }
    every_key: set[tuple[str, ...]] = {
        tuple(cast("dict[str, str]", row["Tooltip"]))
        for unit in (CAPEX, OPEX)
        for row in composition_rows(unit, LINES, FOUND)[0]
    }
    assert len(every_key) == 1


def test_a_segment_too_narrow_for_its_value_has_no_label() -> None:
    rows, _ = composition_rows(OPEX, LINES, FOUND)
    narrow = [row for row in rows if float(str(row["Share"])) / 4000 < 0.08]

    assert narrow
    assert not any(row["Label"] for row in narrow)
    assert all(row["Label"] for row in rows if row not in narrow)


@pytest.mark.parametrize("unit", UNITS)
@pytest.mark.parametrize("theme", ["light", "dark", None])
def test_composition_chart_has_one_unit_round_ticks_a_fixed_color_per_category_and_labels(
    unit: Unit, theme: str | None
) -> None:
    spec = composition_chart(unit, LINES, FOUND, theme).to_dict()
    bars, labels = spec["layer"]
    encoding = bars["encoding"]
    names = categories(unit, LINES)
    rows, ticks = composition_rows(unit, LINES, FOUND)

    assert bars["mark"]["type"] == "bar"
    assert bars["mark"]["tooltip"] == {"expr": "datum.Tooltip"}
    assert encoding["x"]["title"] == unit.amount_unit
    assert encoding["x"]["stack"] == "zero"
    assert encoding["x"]["axis"] == {"format": ",.0f", "values": ticks}
    assert encoding["x"]["scale"] == {"domain": [0, ticks[-1]], "nice": False}
    assert encoding["y"]["sort"] == bar_order(rows)
    assert encoding["color"]["scale"]["domain"] == names
    assert encoding["color"]["scale"]["range"] == [color for color, _ in SEGMENT_COLORS[theme or "light"][: len(names)]]
    assert encoding["color"]["legend"] == {"orient": "top", "title": None}
    assert labels["mark"]["type"] == "text"
    assert labels["mark"]["tooltip"] == {"expr": "datum.Tooltip"}
    assert labels["encoding"]["x"]["field"] == "Middle"
    assert labels["encoding"]["text"]["field"] == "Label"
    assert labels["encoding"]["color"] == {"field": "Ink", "scale": None, "type": "nominal"}


# Smoke run of the page


@pytest.fixture
def reads(replace_reads: Callable[..., None]) -> dict[str, Any]:
    """Replace the Infrahub reads.

    Set `artifact` to None to simulate an artifact not generated yet, and `circuit_schema` to False to
    simulate a main branch without the circuit schema. `generated` records each generation request.
    """
    state: dict[str, Any] = {"artifact": to_csv(LINES), "circuit_schema": True, "generated": []}

    def fake_run_query(name: str, variables: dict[str, Any] | None = None, branch: str = "main", **_: Any) -> dict:  # noqa: ANN401
        assert (name, branch) == ("cost_of_service", "main")
        return stored_only(SEEDED)

    def fake_run_async(read: Callable[..., Any], *args: Any) -> Any:  # noqa: ANN401
        if read is read_circuits:
            assert args == ("main",)
            return build_circuit_data() if state["circuit_schema"] else None
        return run_async_on_fixture(read, *args)

    def fake_read_artifact(artifact_name: str, branch: str = "main", **_: Any) -> str | None:  # noqa: ANN401
        assert (artifact_name, branch) == (ARTIFACT_NAME, "main")
        artifact: str | None = state["artifact"]
        return artifact

    def fake_generate_artifact(artifact_name: str, branch: str = "main", **_: Any) -> Generation:  # noqa: ANN401
        state["generated"].append((artifact_name, branch))
        state["artifact"] = to_csv(LINES)
        return Generation.READY

    replace_reads(
        run_query=fake_run_query,
        read_artifact=fake_read_artifact,
        generate_artifact=fake_generate_artifact,
        run_async=fake_run_async,
    )
    return state


def _select(service: str, unit: Unit | None = None) -> AppTest:
    """Run the page, pick `unit` when given, then the service with identifier `service`."""
    app = AppTest.from_file(PAGE).run(timeout=30)
    if unit:
        app.radio(key="cost-of-service-unit").set_value(unit).run(timeout=30)
    selected = next(found for found in FOUND if found.identifier == service)
    app.selectbox(key="cost-of-service-service").select(selected).run(timeout=30)
    assert not app.exception
    return app


def _expander(app: AppTest, label: str) -> Any:  # noqa: ANN401 - AppTest's expander element
    return next(expander for expander in app.expander if expander.label == label)


def test_page_shows_capex_only_by_default(reads: dict[str, Any]) -> None:
    app = _select("DI-1001")

    assert app.radio(key="cost-of-service-unit").value == CAPEX
    assert app.radio(key="cost-of-service-unit").options == [unit.label for unit in UNITS]
    assert app.selectbox(key="cost-of-service-service").value == DI_1001
    assert "DI-1001 (Northbank, Gold)" in app.selectbox(key="cost-of-service-service").options
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Carried by services (EUR, one-time)", "61,000.00")
    ]
    assert all(metric.help for metric in app.metric)
    captions = [caption.value for caption in app.main.caption]
    assert PAGE_CAPTION in captions
    assert not_carried_text(CAPEX, TOTALS) in captions
    assert len(app.get("vega_lite_chart")) == 1
    paths = app.main.dataframe[0].value.to_dict("records")
    assert [(row["Part"], row["Share (EUR, one-time)"]) for row in paths] == [
        ("switch", "1,200.00"),
        ("router", "2,000.00"),
        ("switch", "1,200.00"),
        ("router", "2,000.00"),
    ]
    assert "Total for DI-1001: **6,400.00 EUR, one-time**" in [element.value for element in app.markdown]
    assert "per month" not in " ".join(element.value for element in (*app.markdown, *app.metric))


def test_page_shows_opex_only_when_switched(reads: dict[str, Any]) -> None:
    app = _select("DI-1001", OPEX)

    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Carried by services (EUR per month)", "9,000.00")
    ]
    assert not_carried_text(OPEX, TOTALS) in [caption.value for caption in app.main.caption]
    paths = app.main.dataframe[0].value.to_dict("records")
    assert [(row["Part"], row["Share (EUR per month)"]) for row in paths] == [
        ("circuit", "1,908.40"),
        ("circuit", "1,908.40"),
    ]
    assert "Total for DI-1001: **3,816.79 EUR per month**" in [element.value for element in app.markdown]
    assert "one-time" not in " ".join(element.value for element in (*app.markdown, *app.metric))


def test_all_services_and_inputs_are_collapsed(reads: dict[str, Any]) -> None:
    app = _select("DI-2001")
    services_panel = _expander(app, "All services")
    inputs_panel = _expander(app, "Inputs and formulas")

    assert not services_panel.proto.expanded
    assert not inputs_panel.proto.expanded
    assert len(services_panel.dataframe[0].value) == 12
    assert len(app.get("download_button")) == 1
    rows = inputs_panel.dataframe[0].value.to_dict("records")
    assert rows == [
        {
            "Input": "Device type: Generic router",
            "Value": "12,000",
            "Unit": "EUR",
            "Label": "demo input",
            "Source file": "data/06_device_type.yml",
        },
        {
            "Input": "Device type: Generic switch",
            "Value": "6,000",
            "Unit": "EUR",
            "Label": "demo input",
            "Source file": "data/06_device_type.yml",
        },
    ]
    text = " ".join(element.value for element in inputs_panel.markdown)
    assert "spread evenly per active interface" in text
    # The worked example stays on DI-1001 whichever service is selected.
    assert "Worked example: DI-1001 (Northbank, Gold)" in text


def test_inputs_of_opex_are_the_circuits(reads: dict[str, Any]) -> None:
    app = _select("DI-2001", OPEX)
    panel = _expander(app, "Inputs and formulas")
    rows = panel.dataframe[0].value.to_dict("records")

    assert len(rows) == 8
    assert {(row["Unit"], row["Label"]) for row in rows} == {("EUR per month", "demo input")}
    assert "in proportion to bandwidth" in " ".join(element.value for element in panel.markdown)


def test_page_says_when_the_csv_is_not_generated_yet(reads: dict[str, Any]) -> None:
    reads["artifact"] = None
    app = _select("DI-2001")

    assert [info.value for info in app.info] == [NOT_GENERATED]
    assert [button.label for button in app.button] == [REGENERATE]
    assert not app.get("download_button")


def test_a_csv_is_current_only_when_it_has_the_page_figures() -> None:
    assert csv_is_current(to_csv(LINES), LINES)
    assert not csv_is_current(to_csv(cost_lines(stored_only(SEEDED))), LINES)


def test_page_says_nothing_about_a_current_csv(reads: dict[str, Any]) -> None:
    app = _select("DI-1001")

    assert not app.warning
    assert not app.info
    assert not app.button


def test_page_says_when_the_csv_is_older_than_its_figures(reads: dict[str, Any]) -> None:
    # The CSV was generated before the circuits were loaded.
    reads["artifact"] = to_csv(cost_lines(stored_only(SEEDED)))
    app = _select("DI-1001")

    assert [warning.value for warning in app.warning] == [STALE]
    assert [button.label for button in app.button] == [REGENERATE]
    assert len(app.get("download_button")) == 1


def test_regenerate_asks_infrahub_for_the_csv_on_main_and_reads_it_again(reads: dict[str, Any]) -> None:
    reads["artifact"] = to_csv(cost_lines(stored_only(SEEDED)))
    app = _select("DI-1001")
    app.button(key="cost-of-service-regenerate").click().run(timeout=30)

    assert not app.exception
    assert reads["generated"] == [(ARTIFACT_NAME, "main")]
    assert not app.warning


def test_page_shows_nothing_about_maintenance_notification_depreciation_or_budgets(
    reads: dict[str, Any],
) -> None:
    app = _select("DI-1001")
    texts = [element.value for element in (*app.markdown, *app.caption, *app.info, *app.warning)]
    texts += [metric.label for metric in app.metric] + [metric.help or "" for metric in app.metric]
    texts += [expander.label for expander in app.expander]

    words = ("maintenance", "notif", "depreciation", "budget", "forecast", "planned utilization", "sla", "branch")
    on_screen = " ".join(texts).lower().replace("not planned utilization", "")
    assert not [word for word in words if word in on_screen]
    assert not app.text_input
    assert not app.number_input


def test_without_the_circuit_schema_capex_is_unchanged(reads: dict[str, Any]) -> None:
    reads["circuit_schema"] = False
    reads["artifact"] = to_csv(cost_lines(stored_only(SEEDED)))
    app = _select("DI-1001")

    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Carried by services (EUR, one-time)", "61,000.00")
    ]
    assert not_carried_text(CAPEX, TOTALS) in [caption.value for caption in app.main.caption]
    assert len(app.get("vega_lite_chart")) == 1
    assert "Total for DI-1001: **6,400.00 EUR, one-time**" in [element.value for element in app.markdown]


def test_without_the_circuit_schema_opex_says_how_to_load_it(reads: dict[str, Any]) -> None:
    reads["circuit_schema"] = False
    app = AppTest.from_file(PAGE).run(timeout=30)
    app.radio(key="cost-of-service-unit").set_value(OPEX).run(timeout=30)

    assert not app.exception
    assert app.radio(key="cost-of-service-unit").options == [unit.label for unit in UNITS]
    assert OPEX_NEEDS_CIRCUITS in [element.value for element in app.markdown]
    assert not app.get("vega_lite_chart")
    assert not app.metric
    assert not app.dataframe
