"""Cost of Service page: what each service costs to deliver, from the demo inputs.

Layout and copy only. The figures come from the stored query `cost_of_service`
on main, the circuit query when the circuit schema is loaded, the footprint of
each active service (Infrahub's path traversal, `circuits.add_footprints`) and
`service_catalog.cost_of_service.cost`, the same queries and functions the
"Cost of service" artifact uses. The download serves the CSV artifact that
Infrahub generated; the page builds no copy of its own. Infrahub does not
generate the CSV again when a circuit changes, so the page compares the stored
CSV with the CSV of its own figures. When the CSV is missing or older, the
page says so and offers a Regenerate button, the only request the page sends
to Infrahub. Every Infrahub read sits in a `st.cache_data(ttl=10)` wrapper that
returns plain data. The page has no input to edit.

A switch shows one unit at a time: CAPEX (hardware, EUR one-time) or OPEX
(circuits, EUR per month). From top to bottom: the CSV status when the CSV
is missing or older; the total the services carry
and the cost no service carries; the composition of each service's cost by
category; the selected service and its paths; then, collapsed, all services
with the CSV download, and the inputs and formulas. Without the circuit schema,
OPEX shows one sentence that says how to load it.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import streamlit as st

from service_catalog.artifact_view import STALE, render_regenerate
from service_catalog.business_impact.blast_radius import MAIN_BRANCH
from service_catalog.business_impact.page_views import CACHE_TTL_S
from service_catalog.cost_of_service.circuits import add_footprints, read_circuits
from service_catalog.cost_of_service.cost import (
    CostLine,
    Service,
    cost_lines,
    has_circuits,
    inputs,
    number_text,
    service_lines,
    services,
    totals,
    with_circuits,
)
from service_catalog.cost_of_service.view import (
    ARTIFACT_NAME,
    CARRIED_LABEL,
    CSV_FILE_NAME,
    NO_SERVICE,
    NOT_GENERATED,
    OPEX,
    OPEX_NEEDS_CIRCUITS,
    PAGE_CAPTION,
    REGENERATE_KEY,
    UNITS,
    Unit,
    composition_chart,
    csv_is_current,
    input_rows,
    left_out_text,
    not_carried_text,
    path_rows,
    service_label,
    service_rows,
    service_total,
    worked_example,
)
from service_catalog.infrahub import read_artifact, run_async, run_query

QUERY_NAME = "cost_of_service"
EXAMPLE_SERVICE = "DI-1001"

UNIT_HELP = "CAPEX is the one-time hardware cost. OPEX is the monthly circuit cost. They are never added together."
PICKER_HELP = "Each service in the catalog with at least one path."
INPUTS_CAPTION = "Values invented for the demo. Change them in their source file; this page does not edit them."
READ_ERROR = "Could not read the cost inputs from Infrahub. The page log has the details."
DOWNLOAD_READ_ERROR = "Could not read the cost of service CSV from Infrahub. The page log has the details."

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Cost of Service", page_icon="💶", layout="wide")


# Infrahub reads, cached for 10 seconds. Each returns plain data.


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def read_cost_data() -> dict[str, Any]:
    """The stored query `cost_of_service` on main."""
    return run_query(QUERY_NAME, branch=MAIN_BRANCH)


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def read_circuit_data() -> dict[str, Any] | None:
    """The circuit query on main, or None when the circuit schema is not loaded."""
    data: dict[str, Any] | None = run_async(read_circuits, MAIN_BRANCH)
    return data


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def read_cost_inputs() -> dict[str, Any]:
    """The stored query and the circuit query on main, with the footprint of each active service."""
    data: dict[str, Any] = run_async(add_footprints, with_circuits(read_cost_data(), read_circuit_data()), MAIN_BRANCH)
    return data


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def read_cost_csv() -> str | None:
    """The "Cost of service" artifact content on main, or None when it is not generated yet."""
    return read_artifact(ARTIFACT_NAME, branch=MAIN_BRANCH)


# Rendering


def read_csv_or_error() -> tuple[str | None, bool]:
    """The CSV content and True when it was read; on a failed read, logs it, shows the error and returns False."""
    try:
        return read_cost_csv(), True
    except Exception:
        logger.exception("Reading the %s artifact failed", ARTIFACT_NAME)
        st.error(DOWNLOAD_READ_ERROR)
        return None, False


def render_file_status(content: str | None, lines: list[CostLine]) -> None:
    """Says when the CSV in Infrahub is missing or older than the page's figures, with a Regenerate button."""
    if content is None:
        st.info(NOT_GENERATED)
    elif not csv_is_current(content, lines):
        st.warning(STALE)
    else:
        return
    render_regenerate(ARTIFACT_NAME, MAIN_BRANCH, REGENERATE_KEY)


def render_download(content: str | None) -> None:
    if content is None:
        return
    st.download_button(
        "Download the cost of service CSV",
        data=content,
        file_name=CSV_FILE_NAME,
        mime="text/csv",
        key="cost-of-service-download",
    )


def render_service(unit: Unit, found: list[Service], lines: list[CostLine]) -> None:
    st.markdown("### Selected service")
    service = st.selectbox(
        "Service", options=found, format_func=service_label, help=PICKER_HELP, key="cost-of-service-service"
    )
    own = service_lines(lines, service.identifier)
    st.dataframe(pd.DataFrame(path_rows(unit, own)), hide_index=True)
    total = number_text(service_total(unit, own), grouped=True, cents=True)
    st.markdown(f"Total for {service.identifier}: **{total} {unit.amount_unit}**")


def render_all_services(unit: Unit, found: list[Service], lines: list[CostLine], content: str | None) -> None:
    with st.expander("All services"):
        st.dataframe(pd.DataFrame(service_rows(unit, lines, found)), hide_index=True)
        render_download(content)


def render_inputs(unit: Unit, data: dict[str, Any], found: list[Service], lines: list[CostLine]) -> None:
    example = next((service for service in found if service.identifier == EXAMPLE_SERVICE), found[0])
    with st.expander("Inputs and formulas"):
        st.caption(INPUTS_CAPTION)
        st.dataframe(pd.DataFrame(input_rows(unit, inputs(data))), hide_index=True)
        st.markdown(unit.method)
        st.markdown(worked_example(unit, lines, example))


def render_page() -> None:
    st.markdown("# Cost of service")
    st.caption(PAGE_CAPTION)
    try:
        data = read_cost_inputs()
    except Exception:
        logger.exception("Reading the %s query failed", QUERY_NAME)
        st.error(READ_ERROR)
        return
    lines = cost_lines(data)
    content, read = read_csv_or_error()
    if read:
        render_file_status(content, lines)
    found = [service for service in services(data) if service.paths]
    if not found:
        st.write(NO_SERVICE)
        return
    unit = st.radio(
        "Cost",
        UNITS,
        format_func=lambda unit: unit.label,
        horizontal=True,
        help=UNIT_HELP,
        key="cost-of-service-unit",
    )
    if unit == OPEX and not has_circuits(data):
        st.write(OPEX_NEEDS_CIRCUITS)
        return
    carried = number_text(service_total(unit, lines), grouped=True, cents=True)
    st.metric(f"{CARRIED_LABEL} ({unit.amount_unit})", carried, help=unit.carried_help)
    st.caption(not_carried_text(unit, totals(data)))
    if text := left_out_text(unit, lines):
        st.caption(text)
    st.markdown(f"#### Cost per service by category ({unit.amount_unit})")
    st.altair_chart(composition_chart(unit, lines, found, st.context.theme.type), width="stretch")
    render_service(unit, found, lines)
    render_all_services(unit, found, lines, content)
    render_inputs(unit, data, found, lines)


render_page()
