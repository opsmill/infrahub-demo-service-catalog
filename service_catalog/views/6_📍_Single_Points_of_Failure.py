"""Single points of failure page: on the current network, the Gold services that depend on a single device.

Layout only. The reads and the rendering live in `service_catalog.business_impact.page_views`.
"""

from __future__ import annotations

import streamlit as st

from service_catalog.business_impact.page_views import SIDEBAR_CAPTION, render_single_points

st.set_page_config(page_title="Single points of failure", page_icon="📍", layout="wide")

st.markdown("# Single points of failure")
st.sidebar.caption(SIDEBAR_CAPTION)
render_single_points()
