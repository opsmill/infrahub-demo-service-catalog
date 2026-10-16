"""The file status and the Regenerate button of the pages that show an artifact's figures.

The Cost of Service and Customer notification pages compute their figures from
the live data, with the same functions as the transforms of their artifacts.
Infrahub generates an artifact again only when a node of its stored query
result changes, so the file it stores can be older than the page. When the two
differ, the page says so and offers a button that asks Infrahub to generate
the file again (`infrahub.generate_artifact`), then reads the page again.
"""

from __future__ import annotations

import logging

import streamlit as st

from service_catalog import infrahub

STALE = "The file in Infrahub is older than the figures on this page"
REGENERATE = "Regenerate"
REGENERATE_HELP = "Asks Infrahub to generate the file again from the current data."
REGENERATING = "Infrahub is generating the file"
REGENERATE_FAILED = "Infrahub could not generate the file. The task log has the details."
REGENERATE_TIMEOUT = "Infrahub did not finish the file within a minute. Read this page again later."
REGENERATE_ERROR = "Could not ask Infrahub to generate the file. The page log has the details."

logger = logging.getLogger(__name__)


def render_regenerate(artifact_name: str, branch: str, key: str) -> None:
    """The Regenerate button: generate the artifact on `branch`, wait for it, then read the page again."""
    if not st.button(REGENERATE, help=REGENERATE_HELP, key=key):
        return
    try:
        with st.spinner(REGENERATING):
            outcome: infrahub.Generation = infrahub.generate_artifact(artifact_name, branch=branch)
    except Exception:
        logger.exception("Generating the %s artifact on %s failed", artifact_name, branch)
        st.error(REGENERATE_ERROR)
        return
    if outcome == infrahub.Generation.FAILED:
        st.error(REGENERATE_FAILED)
        return
    if outcome == infrahub.Generation.TIMEOUT:
        st.warning(REGENERATE_TIMEOUT)
        return
    st.cache_data.clear()
    st.rerun()
