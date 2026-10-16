"""What the Cost of Service page shows, from the cost lines, totals and inputs of `cost.py`.

Plain functions that build the page's labels, help texts, table rows and chart, so
the page's choices are unit-tested without Streamlit or a server.

The page shows one unit at a time: CAPEX (hardware, EUR one-time) or OPEX
(circuits, EUR per month). The two are never shown side by side or added together.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import altair as alt

from .cost import (
    CIRCUIT,
    ONE_TIME,
    PER_MONTH,
    ROUTER,
    SWITCH,
    CostInput,
    CostLine,
    CostTotals,
    Service,
    number_text,
    service_lines,
    shares,
    to_csv,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ARTIFACT_NAME = "cost-of-service"
CSV_FILE_NAME = "cost-of-service.csv"
PAGE_CAPTION = (
    "A service's cost follows its paths through the network: its share of each device and circuit it uses, "
    "by actual utilization, not planned utilization. Every input is a demo input."
)
NOT_GENERATED = "The cost of service CSV is not generated yet"
NO_SERVICE = "No service has a path yet"
OPEX_NEEDS_CIRCUITS = "OPEX needs the circuit schema: `invoke seed` loads it with the upstream circuits."
CARRIED_LABEL = "Carried by services"
REGENERATE_KEY = "cost-of-service-regenerate"
ROUNDING_RULE = (
    "Each line is shown rounded to the cent. A sum adds the unrounded shares and rounds once, so it can "
    "differ by a cent from the sum of the rounded lines."
)

# The composition chart groups the parts of each path into categories. A new part kind adds a category here.
SWITCHING = "Switching"
ROUTING = "Routing"
UPSTREAM_CIRCUITS = "Upstream circuits"
PART_CATEGORIES = {SWITCH: SWITCHING, ROUTER: ROUTING, CIRCUIT: UPSTREAM_CIRCUITS}
# Categorical colors in a fixed order, one step for each Streamlit theme. The order passes the
# color vision deficiency checks for neighbouring segments in both themes. Each color comes with the
# text color of a value printed inside it: white or near black, whichever has the higher contrast.
WHITE_TEXT = "#ffffff"
DARK_TEXT = "#1a1a1a"
SEGMENT_COLORS: dict[str, tuple[tuple[str, str], ...]] = {
    "light": (
        ("#2a78d6", WHITE_TEXT),
        ("#eb6834", DARK_TEXT),
        ("#1baf7a", DARK_TEXT),
        ("#eda100", DARK_TEXT),
        ("#e87ba4", DARK_TEXT),
    ),
    "dark": (
        ("#3987e5", DARK_TEXT),
        ("#d95926", DARK_TEXT),
        ("#199e70", DARK_TEXT),
        ("#c98500", DARK_TEXT),
        ("#d55181", DARK_TEXT),
    ),
}
# The page background of each Streamlit theme, drawn between segments as a gap.
SURFACE = {"light": "#ffffff", "dark": "#0e1117"}
BAR_SIZE = 20
ROW_HEIGHT = 30
CHART_PADDING = 60
# The EUR axis has a few round ticks: a step of 1, 2 or 5 x 10^n, about five of them.
AXIS_TICKS = 5
# A segment prints its value only when it takes at least this part of the axis, so the label fits inside it.
MIN_LABEL_PART = 0.08
LABEL_FONT_SIZE = 11


@dataclass(frozen=True)
class Unit:
    """One of the two units the page shows, one at a time.

    `line_unit` is the unit of the cost lines it sums; `divisor` names what a share's input is divided by.
    The page's switch hands back a copy of the selected unit, so units are compared with `==`, not `is`.
    """

    label: str
    amount_unit: str
    line_unit: str
    divisor: str
    carried_help: str
    method: str


CAPEX = Unit(
    label="CAPEX: hardware, one-time",
    amount_unit="EUR, one-time",
    line_unit=ONE_TIME,
    divisor="active interfaces",
    carried_help=(
        "Sum of the hardware shares of every service: each device's list price / its interfaces with status "
        "active, for every device on every path. Lines without a share are left out.\n\n" + ROUNDING_RULE
    ),
    method=(
        "**How the hardware cost is spread over the services**\n\n"
        "- A device's list price is spread evenly per active interface: list price (EUR) / interfaces with "
        "status active. Each path of a service takes the share of its switch and of its edge router.\n"
        "- What no service carries stays a separate figure: the share of the upstream interfaces of the edge "
        "routers in use, and the list price of each edge router that carries no service."
    ),
)
OPEX = Unit(
    label="OPEX: circuits, per month",
    amount_unit="EUR per month",
    line_unit=PER_MONTH,
    divisor="Mbit/s",
    carried_help=(
        "Sum of the circuit shares of every service: each circuit's monthly cost x the service's bandwidth / "
        "the bandwidth of every service path through its edge router. Lines without a share are left out.\n\n"
        + ROUNDING_RULE
    ),
    method=(
        "**How the circuit cost is spread over the services**\n\n"
        "- A circuit's monthly cost is spread in proportion to bandwidth: monthly cost (EUR) x the service's "
        "bandwidth / the bandwidth of every service path through the circuit's edge router.\n"
        "- What no service carries stays a separate figure: the circuit of each edge router that carries no "
        "service."
    ),
)
UNITS = (CAPEX, OPEX)


def csv_is_current(stored: str, lines: Iterable[CostLine]) -> bool:
    """True when the CSV Infrahub stored is the CSV of `lines`, the figures the page shows."""
    return stored.strip() == to_csv(lines).strip()


def service_label(service: Service) -> str:
    """ "DI-1001 (Northbank, Gold)": the service identifier with its customer and tier."""
    details = ", ".join(part for part in (service.customer, service.tier) if part)
    return f"{service.identifier} ({details})" if details else service.identifier


def service_total(unit: Unit, lines: Sequence[CostLine]) -> float:
    """The sum of the shares of `lines` in `unit`, rounded once."""
    summed = shares(lines)
    return summed.hardware if unit == CAPEX else summed.circuit


def not_carried_text(unit: Unit, totals: CostTotals) -> str:
    """One sentence with the cost that no service carries in `unit`, and where it comes from."""
    idle = len(totals.unused_routers)
    routers = f"{idle} edge {'router' if idle == 1 else 'routers'} with no service"
    if unit == CAPEX:
        total, upstream, unused = (
            number_text(value, grouped=True, cents=True)
            for value in (totals.not_carried_one_time, totals.upstream_total, totals.unused_total)
        )
        return (
            f"Not carried by any service: {total} EUR one-time, from the upstream interfaces of the edge routers "
            f"in use ({upstream}) and the {routers} ({unused})."
        )
    monthly = number_text(totals.not_carried_monthly, grouped=True, cents=True)
    return f"Not carried by any service: {monthly} EUR per month, the circuits of the {routers}."


def left_out_text(unit: Unit, lines: Iterable[CostLine]) -> str | None:
    """ "Left out of the figures: 2 lines with no circuit.", or None when no line of `unit` is left out."""
    counted = Counter(line.note for line in lines if line.unit == unit.line_unit and line.note)
    parts = [f"{count} {'line' if count == 1 else 'lines'} with {note}" for note, count in sorted(counted.items())]
    return f"Left out of the figures: {', '.join(parts)}." if parts else None


def path_rows(unit: Unit, lines: Iterable[CostLine]) -> list[dict[str, str]]:
    """The path table of one service in `unit`: one row per path and part, the backup path named as such."""
    return [
        {
            "Path": line.path,
            "Part": line.part,
            "Item": line.item,
            f"Input ({unit.amount_unit})": number_text(line.input, grouped=True),
            f"Divisor ({unit.divisor})": number_text(line.divisor, grouped=True),
            f"Share ({unit.amount_unit})": number_text(line.share, grouped=True, cents=True) or line.note,
        }
        for line in lines
        if line.unit == unit.line_unit
    ]


def service_rows(unit: Unit, lines: Sequence[CostLine], found: Iterable[Service]) -> list[dict[str, object]]:
    """The all-services table in `unit`: one row per service, by service identifier."""
    return [
        {
            "Service": service.identifier,
            "Customer": service.customer,
            "Tier": service.tier,
            "Bandwidth (Mbit/s)": number_text(service.bandwidth, grouped=True),
            "Paths": len(service.paths),
            f"Total ({unit.amount_unit})": number_text(
                service_total(unit, service_lines(lines, service.identifier)), grouped=True, cents=True
            ),
        }
        for service in sorted(found, key=lambda service: service.identifier)
    ]


# The composition chart


def category(part: str) -> str:
    """The chart category of a path part: switch is Switching, router is Routing, circuit is Upstream circuits."""
    return PART_CATEGORIES[part]


def categories(unit: Unit, lines: Iterable[CostLine]) -> list[str]:
    """The categories of `unit` in the order of the part kinds, so each keeps its color."""
    found = {category(line.part) for line in lines if line.unit == unit.line_unit}
    return [name for name in PART_CATEGORIES.values() if name in found]


def calculation(line: CostLine, bandwidth: int) -> str:
    """How one share is computed, with its numbers.

    "6,000 / 5 active interfaces = 1,200" for a device, "2,500 x 10,000 / 13,100 Mbit/s = 1,908.40" for a circuit.
    """
    item, divisor, share = (number_text(value, grouped=True) for value in (line.input, line.divisor, line.share))
    if line.part == CIRCUIT:
        return f"{item} x {number_text(bandwidth, grouped=True)} / {divisor} Mbit/s = {share}"
    return f"{item} / {divisor} active interfaces = {share}"


def axis_ticks(top: float) -> list[float]:
    """A few round ticks from 0 to at least `top`: a step of 1, 2 or 5 x 10^n, about five ticks."""
    if top <= 0:
        return [0.0, 1.0]
    rough = top / AXIS_TICKS
    power = 10 ** math.floor(math.log10(rough))
    step = next(power * factor for factor in (1, 2, 5, 10) if power * factor >= rough)
    count = math.ceil(top / step - 1e-9)
    return [float(step * index) for index in range(count + 1)]


def _segment_tooltip(unit: Unit, service: Service, name: str, own: Sequence[CostLine]) -> dict[str, str]:
    """The tooltip of one segment: the service, the calculation of each item in the category, then the totals.

    Every segment has the same keys. Streamlit puts all rows in one table, so a key that only some
    segments have would show as an empty row on all the others.
    """
    items = [line for line in own if category(line.part) == name]
    return {
        "Service": service.identifier,
        "Customer": service.customer,
        "Tier": service.tier,
        "Category": name,
        "Calculation": "; ".join(f"{line.item}: {calculation(line, service.bandwidth)}" for line in items),
        "Category total": f"{number_text(service_total(unit, items), grouped=True)} {unit.amount_unit}",
        "Service total": f"{number_text(service_total(unit, own), grouped=True)} {unit.amount_unit}",
    }


def composition_rows(
    unit: Unit, lines: Sequence[CostLine], found: Iterable[Service]
) -> tuple[list[dict[str, object]], list[float]]:
    """One stacked bar per service in `unit`, by category, highest total first, then by service identifier.

    Returns the segments and the ticks of the axis. Each segment carries its place in the category order,
    where its middle sits on the axis, its value label (empty when the segment is too narrow to hold it)
    and its tooltip with the calculation of each item.
    """
    order = categories(unit, lines)
    bars = []
    for service in found:
        own = [
            line
            for line in service_lines(lines, service.identifier)
            if line.unit == unit.line_unit and not line.note and line.share is not None
        ]
        by_category: dict[str, float] = defaultdict(float)
        for line in own:
            by_category[category(line.part)] += line.share or 0.0
        bars.append((service, own, service_total(unit, own), by_category))
    bars.sort(key=lambda bar: (-bar[2], bar[0].identifier))
    ticks = axis_ticks(max((bar[2] for bar in bars), default=0.0))
    rows: list[dict[str, object]] = []
    for service, own, _, by_category in bars:
        start = 0.0
        for position, name in enumerate(order):
            share = by_category[name]
            if not share:
                continue
            rows.append(
                {
                    "Bar": service.identifier,
                    "Segment": name,
                    "Order": position,
                    "Share": round(share, 2),
                    "Middle": round(start + share / 2, 2),
                    "Label": number_text(share, grouped=True) if share / ticks[-1] >= MIN_LABEL_PART else "",
                    "Tooltip": _segment_tooltip(unit, service, name, own),
                }
            )
            start += share
    return rows, ticks


def bar_order(rows: Iterable[dict[str, object]]) -> list[str]:
    """The bars in the order of their first row."""
    return list(dict.fromkeys(str(row["Bar"]) for row in rows))


def composition_chart(
    unit: Unit, lines: Sequence[CostLine], found: Iterable[Service], theme: str | None = None
) -> alt.LayerChart:
    """The composition chart of `unit`: a horizontal stacked bar per service, one segment per category.

    The value of each wide segment is printed inside it. Hovering a segment shows its tooltip: one row per
    item with the calculation of its share.
    """
    rows, ticks = composition_rows(unit, lines, found)
    segments = categories(unit, lines)
    mode = theme if theme in SEGMENT_COLORS else "light"
    colors = SEGMENT_COLORS[mode][: len(segments)]
    values = [{**row, "Ink": colors[int(str(row["Order"]))][1]} for row in rows]
    bars = bar_order(rows)
    tooltip = alt.ExprRef(expr="datum.Tooltip")
    y = alt.Y("Bar:N", sort=bars, title=None)
    base = alt.Chart(alt.Data(values=values))
    segment_bars = base.mark_bar(size=BAR_SIZE, stroke=SURFACE[mode], strokeWidth=1, tooltip=tooltip).encode(
        x=alt.X(
            "Share:Q",
            stack="zero",
            title=unit.amount_unit,
            scale=alt.Scale(domain=[0, ticks[-1]], nice=False),
            axis=alt.Axis(format=",.0f", values=ticks),
        ),
        y=y,
        color=alt.Color(
            "Segment:N",
            scale=alt.Scale(domain=segments, range=[color for color, _ in colors]),
            legend=alt.Legend(title=None, orient="top"),
        ),
        order=alt.Order("Order:Q"),
    )
    labels = base.mark_text(fontSize=LABEL_FONT_SIZE, tooltip=tooltip).encode(
        x=alt.X("Middle:Q"),
        y=y,
        text=alt.Text("Label:N"),
        color=alt.Color("Ink:N", scale=None),
    )
    chart: alt.LayerChart = alt.layer(segment_bars, labels).properties(
        height=ROW_HEIGHT * max(len(bars), 1) + CHART_PADDING
    )
    return chart


# Inputs and formulas


def input_rows(unit: Unit, found: Iterable[CostInput]) -> list[dict[str, str]]:
    """The inputs of `unit`: each input value with its "demo input" label and its source file."""
    return [
        {
            "Input": f"{item.kind}: {item.name}",
            "Value": number_text(item.value, grouped=True) or "not set",
            "Unit": "EUR" if item.unit == ONE_TIME else "EUR per month",
            "Label": item.label,
            "Source file": item.source,
        }
        for item in found
        if item.unit == unit.line_unit
    ]


def _example_term(line: CostLine, bandwidth: int) -> str:
    if line.share is None:
        return f"- {line.path}, {line.part} {line.item}: {line.note}"
    share = number_text(line.share, grouped=True, cents=True)
    if line.part == CIRCUIT:
        return (
            f"- {line.path}, circuit {line.item}: {number_text(line.input, grouped=True)} EUR per month x "
            f"{number_text(bandwidth, grouped=True)} Mbit/s / {number_text(line.divisor, grouped=True)} Mbit/s "
            f"through its edge router = {share} EUR per month"
        )
    return (
        f"- {line.path}, {line.part} {line.item}: {number_text(line.input, grouped=True)} EUR / {line.divisor} active "
        f"interfaces = {share} EUR"
    )


def worked_example(unit: Unit, lines: Sequence[CostLine], service: Service) -> str:
    """The shares of one service in `unit` with their numbers, one line per path and part, then its total."""
    own = [line for line in service_lines(lines, service.identifier) if line.unit == unit.line_unit]
    return "\n".join(
        [
            f"**Worked example: {service_label(service)}, {number_text(service.bandwidth, grouped=True)} Mbit/s**",
            "",
            *(_example_term(line, service.bandwidth) for line in own),
            "",
            f"Together: {number_text(service_total(unit, own), grouped=True, cents=True)} {unit.amount_unit}.",
        ]
    )
