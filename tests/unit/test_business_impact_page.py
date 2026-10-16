"""Smoke test of the Planned maintenance and Single points of failure pages with Streamlit's AppTest.

The Infrahub reads are replaced with the seed-shaped query fixture from
`builders.py`, with the second path `invoke seed` adds to each Paris
Gold service, and the path traversal is answered from that fixture, so the
pages render without a server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from streamlit.testing.v1 import AppTest

from service_catalog.business_impact.page_views import distinct_labels

from .builders import REPO_ROOT, build_seeded_q1, proposed_change, run_async_on_fixture

if TYPE_CHECKING:
    from collections.abc import Callable

PAGE = str(REPO_ROOT / "service_catalog" / "views" / "3_📊_Planned_Maintenance.py")
SINGLE_POINTS_PAGE = str(REPO_ROOT / "service_catalog" / "views" / "6_📍_Single_Points_of_Failure.py")

STATUSES_BY_BRANCH = {
    "main": {},
    "maint-rb01-par01": {"rb01-par01": "maintenance"},
    "maint-sw01-bru01": {"sw01-bru01": "maintenance"},
}


PROPOSED_CHANGES = [
    proposed_change("Implement service di-3001", "implement_di-3001", ["service_request"]),
    proposed_change("Paris router 1 maintenance", "maint-rb01-par01"),
    proposed_change("Brussels switch 1 maintenance", "maint-sw01-bru01"),
]


@pytest.fixture
def reads(replace_reads: Callable[..., None]) -> list[tuple[str, str]]:
    """Replace the Infrahub reads and record (read, branch) calls."""
    calls: list[tuple[str, str]] = []

    def fake_run_query(name: str, variables: dict[str, Any] | None = None, branch: str = "main") -> dict[str, Any]:
        calls.append((name, branch))
        return build_seeded_q1(STATUSES_BY_BRANCH[branch])

    def fake_filter_nodes(kind: type, filters: dict[str, Any] | None = None, branch: str = "main", **_: Any) -> list:  # noqa: ANN401
        calls.append((kind.__name__, branch))
        assert filters == {"state__value": "open"}
        return PROPOSED_CHANGES

    replace_reads(run_query=fake_run_query, filter_nodes=fake_filter_nodes, run_async=run_async_on_fixture)
    return calls


def _metrics(app: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in app.metric}


def _markdown(app: AppTest) -> list[str]:
    return [element.value for element in app.markdown]


AFFECTED_COLUMNS = [
    "Customer",
    "Tier",
    "Service",
    "Paths on the current network",
    "Paths during the change",
    "Status",
    "Rule",
]
TILE_LABELS = ["Customers affected", "Gold services at risk", "Services down"]
PAGE_MONEY_WORDS = ("eur", "€", "sla", "credit", "contract value")


def test_page_opens_on_paris_router_1_maintenance(reads: list[tuple[str, str]]) -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)

    assert not app.exception
    picker = app.sidebar.selectbox(key="business-impact-change")
    assert list(picker.options) == [
        "Current network",
        "Brussels switch 1 maintenance",
        "Paris router 1 maintenance",
    ]
    assert picker.value == "Paris router 1 maintenance"
    assert (
        "## 3 Gold services for Helix Health and Northbank have fewer separate paths during this change"
        in _markdown(app)
    )
    assert [caption.value for caption in app.main.caption] == [
        "Paris router 1 maintenance · found in a proposed change, before merge",
        "Counted",
        "Counted",
        "Counted",
    ]
    assert _metrics(app) == {"Customers affected": "4", "Gold services at risk": "3", "Services down": "2"}
    assert [(expander.label, expander.proto.expanded) for expander in app.expander] == [("Affected services", True)]
    table = app.dataframe[0].value
    assert list(table.columns) == AFFECTED_COLUMNS
    assert table.to_dict("records") == [
        dict(zip(AFFECTED_COLUMNS, row, strict=True))
        for row in (
            ("Northbank", "Gold", "DI-1001", 2, 1, "at risk", 1),
            ("Northbank", "Gold", "DI-1002", 2, 1, "at risk", 1),
            ("Helix Health", "Gold", "DI-1003", 2, 1, "at risk", 1),
            ("Maison Verte", "Silver", "DI-1004", 1, 0, "down", 0),
            ("Rapid Freight", "Bronze", "DI-1006", 1, 0, "down", 0),
        )
    ]
    assert ("business_impact_services", "maint-rb01-par01") in reads
    assert ("business_impact_services", "main") in reads


def test_page_on_current_network(reads: list[tuple[str, str]]) -> None:
    """No service is affected, and the headline has no caption: "Current network" is no proposed change."""
    app = AppTest.from_file(PAGE).run(timeout=30)
    app.sidebar.selectbox(key="business-impact-change").select_index(0).run(timeout=30)

    assert not app.exception
    assert "## No service is affected" in _markdown(app)
    assert _metrics(app) == {"Customers affected": "0", "Gold services at risk": "0", "Services down": "0"}
    assert [caption.value for caption in app.main.caption] == ["Counted", "Counted", "Counted"]


def test_page_on_brussels_switch_1_maintenance(reads: list[tuple[str, str]]) -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    app.sidebar.selectbox(key="business-impact-change").select_index(1).run(timeout=30)

    assert not app.exception
    assert "## 1 Gold service for Helix Health has no path during this change" in _markdown(app)
    assert _metrics(app) == {"Customers affected": "3", "Gold services at risk": "0", "Services down": "3"}
    table = app.dataframe[0].value
    assert list(table["Service"]) == ["DI-2001", "DI-2003", "DI-2005"]
    assert list(table["Status"]) == ["down", "down", "down"]


def _copy(app: AppTest) -> list[str]:
    """Every on-screen string the page writes, including help texts and table headers."""
    return [
        *_markdown(app),
        *(caption.value for caption in app.caption),
        *(metric.label for metric in app.metric),
        *(metric.value for metric in app.metric),
        *(str(metric.help or "") for metric in app.metric),
        *(expander.label for expander in app.expander),
        *(error.value for error in app.error),
        *(str(column) for frame in app.dataframe for column in frame.value.columns),
        *(str(value) for frame in app.dataframe for value in frame.value.to_numpy().ravel()),
    ]


def test_on_screen_copy_never_says_branch(reads: list[tuple[str, str]]) -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    texts = [
        *_copy(app),
        app.sidebar.selectbox(key="business-impact-change").help or "",
        app.sidebar.selectbox(key="business-impact-change").label,
    ]

    assert texts
    assert not [text for text in texts if "branch" in text.lower()]


def test_each_page_shows_one_view(reads: list[tuple[str, str]]) -> None:
    """Each page has its own title and no view switch; only Planned maintenance has the proposed change select."""
    planned = AppTest.from_file(PAGE).run(timeout=30)
    single = AppTest.from_file(SINGLE_POINTS_PAGE).run(timeout=30)

    assert not planned.exception
    assert not single.exception
    assert "# Planned maintenance" in _markdown(planned)
    assert "# Single points of failure" in _markdown(single)
    assert not planned.radio
    assert not single.radio
    assert [box.key for box in planned.sidebar.selectbox] == ["business-impact-change"]
    assert not single.sidebar.selectbox
    assert [caption.value for caption in single.sidebar.caption] == [
        "Every figure is counted from the network model: services, customers, tiers and separate paths. "
        "Customers and tiers are demo data."
    ]


def _open_single_points() -> AppTest:
    return AppTest.from_file(SINGLE_POINTS_PAGE).run(timeout=30)


def test_single_points_view(reads: list[tuple[str, str]]) -> None:
    """Headline, the dependency table, and the failure of the first device in it.

    The Paris Gold services have two separate paths, so no Paris device is a single point of failure.
    """
    app = _open_single_points()

    assert not app.exception
    assert not app.error
    markdown = _markdown(app)
    assert "## 2 of 5 Gold services have a single point of failure" in markdown
    assert "#### If Brussels edge router 1 failed now, 1 Gold service for Helix Health would have no path" in markdown
    assert app.main.caption[0].value == (
        "A path is the route a service's traffic takes through the network at a site: it enters through a switch port, "
        "goes through a switch, and leaves through the edge router with the same number. "
        "A device is a single point of failure for a service when every path of the service passes through it."
    )
    table = app.dataframe[0].value
    assert list(table.columns) == ["Device", "Role", "Gold services", "Customers"]
    assert list(table["Device"]) == [
        "Brussels edge router 1",
        "Brussels edge router 2",
        "Brussels switch 1",
        "Brussels switch 2",
    ]
    assert list(app.dataframe[1].value.columns) == AFFECTED_COLUMNS
    assert [(expander.label, expander.proto.expanded) for expander in app.expander] == [("Affected services", True)]
    assert _metrics(app) == {"Customers affected": "3", "Gold services at risk": "0", "Services down": "3"}
    # The view reads the current network only.
    assert not [branch for name, branch in reads if name == "business_impact_services" and branch != "main"]


def test_single_points_view_with_another_device(reads: list[tuple[str, str]]) -> None:
    app = _open_single_points()
    app.selectbox(key="business-impact-device").set_value("Brussels switch 1").run(timeout=30)

    assert not app.exception
    assert "#### If Brussels switch 1 failed now, 1 Gold service for Helix Health would have no path" in _markdown(app)
    assert _metrics(app) == {"Customers affected": "3", "Gold services at risk": "0", "Services down": "3"}


@pytest.mark.parametrize("page", [PAGE, SINGLE_POINTS_PAGE], ids=["planned-maintenance", "single-points-of-failure"])
def test_no_money_or_sla_on_screen(reads: list[tuple[str, str]], page: str) -> None:
    app = AppTest.from_file(page).run(timeout=30)
    texts = [
        *_copy(app),
        *(caption.value for caption in app.sidebar.caption),
        *(str(selectbox.help or "") for selectbox in app.selectbox),
    ]

    assert not app.exception
    assert [metric.label for metric in app.metric] == TILE_LABELS
    assert not [text for text in texts if any(word in text.lower() for word in PAGE_MONEY_WORDS)]


def test_single_points_copy_never_says_branch(reads: list[tuple[str, str]]) -> None:
    app = _open_single_points()
    texts = [*_copy(app), app.selectbox(key="business-impact-device").help or ""]

    assert texts
    assert not [text for text in texts if "branch" in text.lower()]


def test_proposed_change_read_error_falls_back_to_current_network(
    reads: list[tuple[str, str]], replace_reads: Callable[..., None]
) -> None:
    """A failed proposed change read shows a fixed message and a picker with only Current network."""

    def failing_filter_nodes(*_: object, **__: object) -> list:
        message = "proposed changes unreachable on branch main"
        raise RuntimeError(message)

    replace_reads(filter_nodes=failing_filter_nodes)
    app = AppTest.from_file(PAGE).run(timeout=30)

    assert not app.exception
    assert [error.value for error in app.sidebar.error] == [
        "Could not read the proposed changes from Infrahub. The page log has the details."
    ]
    assert list(app.sidebar.selectbox(key="business-impact-change").options) == ["Current network"]
    assert "## No service is affected" in _markdown(app)
    assert not [text for text in _copy(app) if "branch" in text.lower()]


HOME = str(REPO_ROOT / "service_catalog" / "🏠_Home_Page.py")


def test_home_page_links_to_planned_maintenance_and_single_points() -> None:
    app = AppTest.from_file(HOME).run(timeout=30)

    assert not app.exception
    assert "## Understand business impact" in [element.value for element in app.markdown]
    headers = [header.value for header in app.header]
    assert "📊 Planned maintenance" in headers
    assert "📍 Single points of failure" in headers
    keys = [button.key for button in app.button]
    assert "planned_maintenance" in keys
    assert "single_points_of_failure" in keys


def test_home_page_names_the_new_pages_without_money_or_sla() -> None:
    app = AppTest.from_file(HOME).run(timeout=30)
    texts = [element.value for element in app.markdown]

    assert not app.exception
    assert "📣 Customer notification" in [header.value for header in app.header]
    assert "customer_notification" in [button.key for button in app.button]
    assert "💶 Cost of service" in [header.value for header in app.header]
    assert "cost_of_service" in [button.key for button in app.button]
    business_impact = next(text for text in texts if text.startswith("See which customers"))
    assert not [word for word in ("sla", "credit", "contract value", "eur") if word in business_impact.lower()]


PORTAL = str(REPO_ROOT / "service_catalog" / "portal.py")


@pytest.mark.parametrize(
    ("button", "title"),
    [
        ("planned_maintenance", "# Planned maintenance"),
        ("single_points_of_failure", "# Single points of failure"),
    ],
    ids=["planned-maintenance", "single-points-of-failure"],
)
def test_portal_opens_each_business_impact_page(reads: list[tuple[str, str]], button: str, title: str) -> None:
    """Opens the page as a user does, with its button on the Home page."""
    app = AppTest.from_file(PORTAL).run(timeout=30)
    app.button(key=button).click().run(timeout=30)

    assert not app.exception
    assert title in _markdown(app)


def test_options_that_share_a_label_stay_apart() -> None:
    """Two devices with the same description, or two open changes with the same name, can each be selected."""
    assert distinct_labels([("Paris switch 1", "sw01-par01"), ("Core", "sw01-bru01"), ("Core", "sw02-bru01")]) == {
        "Paris switch 1": "sw01-par01",
        "Core (sw01-bru01)": "sw01-bru01",
        "Core (sw02-bru01)": "sw02-bru01",
    }
