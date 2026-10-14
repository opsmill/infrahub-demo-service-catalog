from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Service Catalog",
    page_icon="👋",
)

st.write("# Welcome to Service Catalog! 👋")

st.markdown(
    """
    This portal is designed to facilitate service delivery operations by exposing forms and data in a simplified format.
    You can request new instance of supported service type and track ongoing or active service implementations!
    """,
)


def card(header: str, text: str, button: str, key: str, page: str) -> None:
    """A bordered card with a header, a text and a button that opens `page`."""
    with st.container(border=True):
        st.header(header)
        st.write(text)
        if st.button(button, use_container_width=True, key=key):
            st.switch_page(page)


st.write("## Request new service")

col1, col2 = st.columns(2)

with col1:
    card(
        "🔌 Dedicated Internet",
        "This form will allow you to request the implementation of a new dedicated internet service..",
        "Create",
        "dedicated_internet",
        "views/1_🔌_Dedicated_Internet.py",
    )

with col2:
    card(
        "🛜 Wireless",
        "This form will allow you to request the implementation of a new wireless service.",
        "Create",
        "wireless",
        "views/2_🛜_Wireless.py",
    )


st.write("## View current requests")

card(
    "📦 Service requests",
    "You will find on this page all services requests opened. For the one delivered you'll also find allocated assets.",
    "View",
    "service_requests",
    "views/0_📦_Service_Requests.py",
)


st.write("## Understand business impact")

for header, text, key, page in (
    (
        "📊 Planned maintenance",
        "See which customers and Gold services a proposed change puts at risk or takes down before it merges.",
        "planned_maintenance",
        "views/3_📊_Planned_Maintenance.py",
    ),
    (
        "📍 Single points of failure",
        "See which Gold services depend on a single device, and which would have no path if that device failed now.",
        "single_points_of_failure",
        "views/6_📍_Single_Points_of_Failure.py",
    ),
    (
        "📣 Customer notification",
        "See the customers a proposed change affects, grouped by status, and which ones are notified.",
        "customer_notification",
        "views/4_📣_Customer_Notification.py",
    ),
    (
        "💶 Cost of service",
        "See what each service costs to deliver, by path and part, from demo inputs.",
        "cost_of_service",
        "views/5_💶_Cost_of_Service.py",
    ),
):
    card(header, text, "View", key, page)
