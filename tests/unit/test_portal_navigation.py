"""The portal's sidebar sections, page titles and URLs, and the entry script that builds them."""

from __future__ import annotations

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from service_catalog.navigation import SECTIONS

PORTAL_DIR = Path(__file__).resolve().parents[2] / "service_catalog"
ENTRY = str(PORTAL_DIR / "portal.py")
HOME = PORTAL_DIR / "🏠_Home_Page.py"


def test_sidebar_sections_and_page_titles() -> None:
    assert {section: [page.title for page in pages] for section, pages in SECTIONS.items()} == {
        "Service catalog": ["Home", "Service Requests", "Dedicated Internet", "Wireless"],
        "Business impact": [
            "Planned maintenance",
            "Single points of failure",
            "Customer notification",
            "Cost of service",
        ],
    }


def test_business_impact_url_paths() -> None:
    assert [page.url_path for page in SECTIONS["Business impact"]] == [
        "planned-maintenance",
        "single-points-of-failure",
        "customer-notification",
        "cost-of-service",
    ]


def test_every_page_has_a_file_and_a_unique_url_path() -> None:
    pages = [page for section in SECTIONS.values() for page in section]
    url_paths = [page.url_path for page in pages]

    assert [page.path for page in pages if not (PORTAL_DIR / page.path).is_file()] == []
    assert len(set(url_paths)) == len(url_paths)
    assert [page.title for page in pages if page.default] == ["Home"]


def test_every_page_file_is_in_the_navigation() -> None:
    """A page file left out of the sections cannot be opened: only the navigation lists pages."""
    listed = {page.path for section in SECTIONS.values() for page in section}
    files = {f"views/{path.name}" for path in (PORTAL_DIR / "views").glob("*.py") if path.name != "__init__.py"}

    assert files <= listed


def test_no_pages_folder_next_to_the_entry_script() -> None:
    """Streamlit runs the first session after a start in folder-pages mode when `pages/` sits next to the
    entry script, so a link such as /single-points-of-failure showed "Page not found" before the page."""
    assert not (PORTAL_DIR / "pages").exists()


def test_home_page_buttons_open_pages_in_the_navigation() -> None:
    listed = {page.path for section in SECTIONS.values() for page in section}
    # The home page passes each button's target page to `card`, which calls `st.switch_page` with it.
    targets = re.findall(r'"(views/[^"]+\.py)"', HOME.read_text(encoding="utf-8"))

    assert len(targets) == 7
    assert [target for target in targets if target not in listed] == []


def test_entry_script_opens_the_home_page() -> None:
    app = AppTest.from_file(ENTRY).run(timeout=30)

    assert not app.exception
    assert "# Welcome to Service Catalog! 👋" in [element.value for element in app.markdown]
