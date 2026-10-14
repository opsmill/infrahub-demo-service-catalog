"""Customer notification page: the customers a proposed change affects, grouped by status.

Layout and copy only. The list is computed from the live data with
`change_impact.read_affected_report`, the function the affected customers
transform uses for the "Affected customers" artifact. The page compares it
with the artifact Infrahub stored on the proposed change's branch. When the
stored artifact is missing, failed or older, the page says so and offers a
Regenerate button, the only request the page sends to Infrahub. The notice
and the grouping come from `service_catalog.business_impact.notification_view`.
Every Infrahub read sits in a `st.cache_data(ttl=10)` wrapper that returns
plain data. No on-screen string uses the word "branch".
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import streamlit as st

from service_catalog import infrahub
from service_catalog.artifact_view import render_regenerate
from service_catalog.business_impact.blast_radius import MAIN_BRANCH
from service_catalog.business_impact.change_impact import read_affected_report
from service_catalog.business_impact.notification_view import (
    ARTIFACT_NAME,
    BLOCKED_CAPTION,
    NO_CUSTOMER_AFFECTED,
    NO_OPEN_CHANGE,
    Notice,
    NotificationList,
    change_options,
    file_notice,
    parse_artifact,
    status_heading,
)
from service_catalog.business_impact.page_views import (
    CACHE_TTL_S,
    PICKER_HELP,
    PROPOSED_CHANGES_READ_ERROR,
    read_proposed_changes,
)
from service_catalog.infrahub import StoredArtifact, read_stored_artifact

PAGE_CAPTION = (
    "Gold customers at risk are notified. Silver and Bronze customers are listed, not notified. "
    "Customers and tiers are demo data."
)
READ_ERROR = "Could not read the affected customers from Infrahub. The page log has the details."
FILE_READ_ERROR = "Could not read the affected customers file from Infrahub. The page log has the details."
REGENERATE_KEY = "customer-notification-regenerate"

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Customer Notification", page_icon="📣", layout="wide")


# Infrahub reads, cached for 10 seconds. Each returns plain data.


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def read_affected_customers(branch: str) -> StoredArtifact | None:
    """The "Affected customers" artifact on `branch`: its status, and its content when it is Ready."""
    return read_stored_artifact(ARTIFACT_NAME, branch=branch)


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def read_live_customers(branch: str) -> dict[str, Any]:
    """The "Affected customers" content for `branch`, computed now from the live data."""
    report: dict[str, Any] = infrahub.run_async(read_affected_report, branch)
    return report


# Rendering


def render_notice(notice: Notice) -> None:
    if notice.error:
        st.error(notice.text)
    elif notice.warning:
        st.warning(notice.text)
    else:
        st.info(notice.text)


def render_file_status(branch: str, live: dict[str, Any]) -> None:
    """Says when the file in Infrahub is missing, failed or older than the list, with a Regenerate button."""
    try:
        stored = read_affected_customers(branch)
    except Exception:
        logger.exception("Reading the %s artifact failed", ARTIFACT_NAME)
        st.error(FILE_READ_ERROR)
        return
    notice = file_notice(stored.content if stored else None, live, branch, failed=stored is not None and stored.failed)
    if notice is None:
        return
    render_notice(notice)
    render_regenerate(ARTIFACT_NAME, branch, REGENERATE_KEY)


def render_list(result: NotificationList) -> None:
    if result.blocked:
        st.caption(BLOCKED_CAPTION)
    if not result.groups:
        st.write(NO_CUSTOMER_AFFECTED)
        return
    for group in result.groups:
        with st.expander(status_heading(group), expanded=True):
            st.dataframe(
                pd.DataFrame(
                    [{"Customer": row.customer, "Tier": row.tier, "Services": row.services} for row in group.rows]
                ),
                hide_index=True,
            )


def render_page() -> None:
    st.markdown("# Customer notification")
    st.caption(PAGE_CAPTION)
    try:
        proposed_changes = read_proposed_changes(MAIN_BRANCH)
    except Exception:
        logger.exception("Reading the proposed changes failed")
        st.error(PROPOSED_CHANGES_READ_ERROR)
        return
    options = change_options(proposed_changes)
    if not options:
        st.write(NO_OPEN_CHANGE)
        return
    label = st.sidebar.selectbox(
        "Proposed change",
        options=[option.label for option in options],
        help=PICKER_HELP,
        key="customer-notification-change",
    )
    entry = next((option for option in options if option.label == label), options[0])
    st.markdown(f"## {entry.label}")
    try:
        live = read_live_customers(entry.branch)
    except Exception:
        logger.exception("Computing the affected customers failed")
        st.error(READ_ERROR)
        return
    render_file_status(entry.branch, live)
    result = parse_artifact(live)
    if result is None:
        st.error(READ_ERROR)
        return
    render_list(result)


render_page()
