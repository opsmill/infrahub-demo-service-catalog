"""Business Impact page: the Blast radius view.

Layout and copy only. Every figure comes from `service_catalog.business_impact.blast_radius`;
every Infrahub read sits in a `st.cache_data(ttl=10)` wrapper keyed by branch that returns
plain data. The page writes nothing to Infrahub. No on-screen string uses the word "branch".
"""

from __future__ import annotations

import logging
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from infrahub_sdk.protocols import CoreProposedChange
from service_catalog.business_impact.blast_radius import (
    IN_THIS_CHANGE,
    MAIN_BRANCH,
    NO_SERVICE_AFFECTED,
    SEGMENT_AFFECTED,
    SEGMENT_NOT_AFFECTED,
    BlastRadius,
    PickerEntry,
    build_blast_radius,
    chart_segments,
    default_picker_index,
    format_eur,
    headline_caption,
    picker_entries,
)
from service_catalog.infrahub import filter_nodes, run_query

QUERY_NAME = "business_impact_services"
CACHE_TTL_S = 10

PICKER_HELP = "Each proposed change keeps its edits apart from the current network. Nothing here has merged."
SIDEBAR_CAPTION = (
    "Counted: counted from the model. "
    "Your input: the model plus a labelled business input, such as a monthly charge or a tier's SLA credit. "
    "Not calculated: outage cost, time saved, ROI, churn. "
    "Customers, tiers and charges are illustrative demo data."
)
CHART_TITLE = "Annual contract value per customer · your input"
ROUTERS_TITLE = "Edge routers ranked by Gold contract value · your input"
MONTHLY_CHARGE_COLUMN = "Monthly charge (EUR) · your input"
READ_ERROR = "Could not read the services from Infrahub. The page log has the details."
PROPOSED_CHANGES_READ_ERROR = "Could not read the proposed changes from Infrahub. The page log has the details."

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Business Impact", page_icon="📊", layout="wide")


# Infrahub reads, cached per branch for 10 seconds. Each returns plain data.


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def read_services(branch: str) -> dict[str, Any]:
    """The stored query `business_impact_services` on `branch`."""
    return run_query(name=QUERY_NAME, branch=branch)


def _tag_names(node: Any) -> list[str]:  # noqa: ANN401 - an SDK node whose protocol has no `tags` field
    tags = getattr(node, "tags", None)
    peers = getattr(tags, "peers", None) or []
    return [str(peer.peer.name.value) for peer in peers]


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def read_proposed_changes(branch: str) -> list[dict[str, Any]]:
    """Open proposed changes with their name, source branch, state and tag names."""
    nodes: list[Any] = filter_nodes(kind=CoreProposedChange, filters={"state__value": "open"}, branch=branch)
    return [
        {
            "name": node.name.value,
            "source_branch": node.source_branch.value,
            "state": node.state.value,
            "tags": _tag_names(node),
        }
        for node in nodes
    ]


# Rendering


def render_sidebar() -> PickerEntry:
    try:
        proposed_changes = read_proposed_changes(MAIN_BRANCH)
    except Exception:
        logger.exception("Reading the proposed changes failed")
        st.sidebar.error(PROPOSED_CHANGES_READ_ERROR)
        proposed_changes = []
    entries = picker_entries(proposed_changes)
    label = st.sidebar.selectbox(
        "Proposed change",
        options=[option.label for option in entries],
        index=default_picker_index(entries),
        help=PICKER_HELP,
        key="business-impact-change",
    )
    st.sidebar.caption(SIDEBAR_CAPTION)
    return next((option for option in entries if option.label == label), entries[0])


def render_chart(result: BlastRadius) -> None:
    order = [value.customer for value in result.customer_values]
    frame = pd.DataFrame(
        [
            {"Customer": row.customer, "Part": row.segment, "EUR": row.annual, "Value": format_eur(row.annual)}
            for row in chart_segments(result.customer_values)
        ]
    )
    chart = (
        alt.Chart(frame, title=CHART_TITLE)
        .mark_bar()
        .encode(
            x=alt.X("sum(EUR):Q", title="EUR per year", axis=alt.Axis(format=",.0f")),
            y=alt.Y("Customer:N", sort=order, title=None),
            color=alt.Color(
                "Part:N",
                scale=alt.Scale(domain=[SEGMENT_AFFECTED, SEGMENT_NOT_AFFECTED], range=["#c0392b", "#b0bec5"]),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            order=alt.Order("Part:N", sort="ascending"),
            tooltip=["Customer:N", "Part:N", "Value:N"],
        )
    )
    st.altair_chart(chart, width="stretch")


def render_affected_services(result: BlastRadius) -> None:
    with st.expander("Affected services"):
        if not result.affected_rows:
            st.write(NO_SERVICE_AFFECTED)
            return
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Service": row.service,
                        "Customer": row.customer,
                        "Tier": row.tier,
                        "Bandwidth": row.bandwidth,
                        "Switch": row.switch,
                        "Edge router": row.edge_router,
                        MONTHLY_CHARGE_COLUMN: row.monthly_charge,
                    }
                    for row in result.affected_rows
                ]
            ),
            hide_index=True,
        )


def render_routers(result: BlastRadius) -> None:
    with st.expander(ROUTERS_TITLE):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Edge router": row.label,
                        "Gold contract value per year (EUR)": format_eur(row.gold_annual),
                        "Marker": IN_THIS_CHANGE if row.in_this_change else "",
                    }
                    for row in result.routers
                ]
            ),
            hide_index=True,
        )


def render_blast_radius(entry: PickerEntry) -> None:
    try:
        data = read_services(entry.branch)
        main_data = data if entry.branch == MAIN_BRANCH else read_services(MAIN_BRANCH)
    except Exception:
        logger.exception("Reading %s failed", QUERY_NAME)
        st.error(READ_ERROR)
        return

    result = build_blast_radius(data, main_data)
    st.markdown(f"## {result.headline}")
    if result.no_services:
        return
    caption = headline_caption(entry.label, result)
    if caption:
        st.caption(caption)

    for column, tile in zip(st.columns(len(result.tiles)), result.tiles, strict=True):
        column.metric(tile.label, tile.value, help=tile.help)
        column.caption(tile.marker)

    render_chart(result)
    render_affected_services(result)
    render_routers(result)


st.markdown("# Business Impact")
render_blast_radius(render_sidebar())
