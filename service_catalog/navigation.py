"""The portal's pages, grouped into the two sidebar sections.

Plain data, so the grouping, titles and URLs are unit-tested without running Streamlit.
`portal.py` turns it into `st.navigation`. Page paths are relative to the `service_catalog` directory.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortalPage:
    path: str
    title: str
    icon: str
    url_path: str
    default: bool = False


SECTIONS: dict[str, tuple[PortalPage, ...]] = {
    "Service catalog": (
        PortalPage("🏠_Home_Page.py", "Home", "🏠", "home", default=True),
        PortalPage("views/0_📦_Service_Requests.py", "Service Requests", "📦", "service-requests"),
        PortalPage("views/1_🔌_Dedicated_Internet.py", "Dedicated Internet", "🔌", "dedicated-internet"),
        PortalPage("views/2_🛜_Wireless.py", "Wireless", "🛜", "wireless"),
    ),
    "Business impact": (
        PortalPage("views/3_📊_Planned_Maintenance.py", "Planned maintenance", "📊", "planned-maintenance"),
        PortalPage(
            "views/6_📍_Single_Points_of_Failure.py", "Single points of failure", "📍", "single-points-of-failure"
        ),
        PortalPage("views/4_📣_Customer_Notification.py", "Customer notification", "📣", "customer-notification"),
        PortalPage("views/5_💶_Cost_of_Service.py", "Cost of service", "💶", "cost-of-service"),
    ),
}
