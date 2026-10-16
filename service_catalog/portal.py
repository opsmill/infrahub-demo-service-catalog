"""Entry point of the Service Catalog portal: builds the grouped sidebar and runs the selected page.

Run it with `streamlit run service_catalog/portal.py`.
"""

from __future__ import annotations

import streamlit as st

from service_catalog.navigation import SECTIONS

pages = {
    section: [
        st.Page(page.path, title=page.title, icon=page.icon, url_path=page.url_path, default=page.default)
        for page in section_pages
    ]
    for section, section_pages in SECTIONS.items()
}

st.navigation(pages).run()
