"""Shared Streamlit reads and rendering for the business impact pages.

The Planned maintenance and Single points of failure pages use the services read
and the rendering below. The Customer notification page uses the proposed
changes read (`read_proposed_changes`) and the picker copy (`PICKER_HELP`,
`PROPOSED_CHANGES_READ_ERROR`).

Layout and copy only. Every figure comes from `blast_radius` and `single_points`;
every Infrahub read sits in a `st.cache_data(ttl=10)` wrapper keyed by branch that returns
plain data. The services read adds the footprint of each active service, the devices
Infrahub's path traversal reaches from it, as the Gold outage guard check does, so the pages and
the check agree. The pages write nothing to Infrahub. No on-screen string uses the word "branch".
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import streamlit as st

from infrahub_sdk.protocols import CoreProposedChange
from service_catalog import infrahub

from .blast_radius import (
    MAIN_BRANCH,
    NO_SERVICE_AFFECTED,
    BlastRadius,
    PickerEntry,
    Tile,
    build_blast_radius,
    default_picker_index,
    headline_caption,
    picker_entries,
)
from .change_impact import QUERY_NAME, add_footprints
from .single_points import SinglePoints, failure_headline, failure_impact, single_points

CACHE_TTL_S = 10

PATHS_CAPTION = (
    "A path is the route a service's traffic takes through the network at a site: it enters through a switch port, "
    "goes through a switch, and leaves through the edge router with the same number. "
    "A device is a single point of failure for a service when every path of the service passes through it."
)
DEPENDENCY_TITLE = "Devices that Gold services depend on"
FAILURE_TITLE = "If this device failed now"
FAILURE_HELP = (
    "Uses a copy of the current network with the selected device not active. The view only reads from Infrahub."
)

PICKER_HELP = "Each proposed change keeps its edits apart from the current network. Nothing here has merged."
SIDEBAR_CAPTION = (
    "Every figure is counted from the network model: services, customers, tiers and separate paths. "
    "Customers and tiers are demo data."
)
READ_ERROR = "Could not read the services from Infrahub. The page log has the details."
PROPOSED_CHANGES_READ_ERROR = "Could not read the proposed changes from Infrahub. The page log has the details."

logger = logging.getLogger(__name__)


def distinct_labels(options: list[tuple[str, str]]) -> dict[str, str]:
    """Each option's label mapped to its key, in order. A label that several options share gets its key added
    in brackets, so every option can be selected."""
    counts: dict[str, int] = {}
    for label, _ in options:
        counts[label] = counts.get(label, 0) + 1
    return {(label if counts[label] == 1 else f"{label} ({key})"): key for label, key in options}


# Infrahub reads, cached per branch for 10 seconds. Each returns plain data.
# They call `infrahub.run_query`, `infrahub.run_async` and `infrahub.filter_nodes` through the module, so
# tests can replace them.


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def read_services(branch: str) -> dict[str, Any]:
    """The stored query `business_impact_services` on `branch`, with the footprint of each active service."""
    data: dict[str, Any] = infrahub.run_query(name=QUERY_NAME, branch=branch)
    with_footprints: dict[str, Any] = infrahub.run_async(add_footprints, data, branch)
    return with_footprints


def _tag_names(node: Any) -> list[str]:  # noqa: ANN401 - an SDK node whose protocol has no `tags` field
    tags = getattr(node, "tags", None)
    peers = getattr(tags, "peers", None) or []
    return [str(peer.peer.name.value) for peer in peers]


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def read_proposed_changes(branch: str) -> list[dict[str, Any]]:
    """Open proposed changes with their name, source branch, state and tag names."""
    nodes: list[Any] = infrahub.filter_nodes(kind=CoreProposedChange, filters={"state__value": "open"}, branch=branch)
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


def render_change_picker() -> PickerEntry:
    """The proposed change select in the sidebar. It falls back to the current network when the read fails."""
    try:
        proposed_changes = read_proposed_changes(MAIN_BRANCH)
    except Exception:
        logger.exception("Reading the proposed changes failed")
        st.sidebar.error(PROPOSED_CHANGES_READ_ERROR)
        proposed_changes = []
    entries = picker_entries(proposed_changes)
    options = distinct_labels([(entry.label, entry.branch) for entry in entries])
    label = st.sidebar.selectbox(
        "Proposed change",
        options=list(options),
        index=default_picker_index(entries),
        help=PICKER_HELP,
        key="business-impact-change",
    )
    st.sidebar.caption(SIDEBAR_CAPTION)
    return entries[list(options).index(label)] if label in options else entries[0]


def _render_tiles(tiles: tuple[Tile, ...]) -> None:
    for column, tile in zip(st.columns(len(tiles)), tiles, strict=True):
        column.metric(tile.label, tile.value, help=tile.help)
        column.caption(tile.marker)


def render_affected_services(result: BlastRadius) -> None:
    with st.expander("Affected services", expanded=True):
        if not result.affected_rows:
            st.write(NO_SERVICE_AFFECTED)
            return
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Customer": row.customer,
                        "Tier": row.tier,
                        "Service": row.service,
                        "Paths on the current network": row.paths_on_main,
                        "Paths during the change": row.paths_during_change,
                        "Status": row.status,
                        "Rule": row.rule,
                    }
                    for row in result.affected_rows
                ]
            ),
            hide_index=True,
        )


def render_blast_radius(entry: PickerEntry) -> None:
    """Services with fewer separate paths during the selected proposed change, and their customers."""
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

    _render_tiles(result.tiles)

    render_affected_services(result)


def render_dependencies(points: SinglePoints) -> None:
    st.markdown(f"#### {DEPENDENCY_TITLE}")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Device": row.label,
                    "Role": row.role,
                    "Gold services": ", ".join(row.gold_services),
                    "Customers": ", ".join(row.customers),
                }
                for row in points.devices
            ]
        ),
        hide_index=True,
    )


def render_single_points() -> None:
    """On the current network, the Gold services that depend on one device, and the effect of one device failing."""
    try:
        data = read_services(MAIN_BRANCH)
    except Exception:
        logger.exception("Reading %s failed", QUERY_NAME)
        st.error(READ_ERROR)
        return

    points = single_points(data)
    st.markdown(f"## {points.headline}")
    st.caption(PATHS_CAPTION)
    if not points.devices:
        return
    render_dependencies(points)

    st.markdown(f"### {FAILURE_TITLE}")
    names = distinct_labels([(row.label, row.name) for row in points.devices])
    label = st.selectbox("Device", options=list(names), help=FAILURE_HELP, key="business-impact-device")
    result = failure_impact(data, names[str(label)])
    st.markdown(f"#### {failure_headline(str(label), result)}")
    _render_tiles(result.tiles)
    render_affected_services(result)
