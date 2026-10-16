"""Planned maintenance page: the services, customers and Gold services a proposed change puts at risk or takes down.

Layout only. The reads and the rendering live in `service_catalog.business_impact.page_views`.
"""

from __future__ import annotations

import streamlit as st

from service_catalog.business_impact.page_views import render_blast_radius, render_change_picker

st.set_page_config(page_title="Planned maintenance", page_icon="📊", layout="wide")

st.markdown("# Planned maintenance")
render_blast_radius(render_change_picker())
