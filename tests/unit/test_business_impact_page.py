"""Smoke test of the Business Impact page with Streamlit's AppTest.

The Infrahub reads are replaced with the seed-shaped query fixture from
`test_blast_radius.py`, so the page renders without a server.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from service_catalog import infrahub

from .test_blast_radius import REPO_ROOT, build_q1

if TYPE_CHECKING:
    from collections.abc import Iterator

PAGE = str(REPO_ROOT / "service_catalog" / "pages" / "3_📊_Business_Impact.py")

STATUSES_BY_BRANCH = {
    "main": {},
    "maint-rb01-par01": {"rb01-par01": "maintenance"},
    "maint-sw01-bru01": {"sw01-bru01": "maintenance"},
}


def _value(value: object) -> SimpleNamespace:
    return SimpleNamespace(value=value)


def _proposed_change(name: str, branch: str, tags: list[str]) -> SimpleNamespace:
    peers = [SimpleNamespace(peer=SimpleNamespace(name=_value(tag))) for tag in tags]
    return SimpleNamespace(
        name=_value(name),
        source_branch=_value(branch),
        state=_value("open"),
        tags=SimpleNamespace(peers=peers),
    )


PROPOSED_CHANGES = [
    _proposed_change("Implement service di-3001", "implement_di-3001", ["service_request"]),
    _proposed_change("Paris router 1 maintenance", "maint-rb01-par01", []),
    _proposed_change("Brussels switch 1 maintenance", "maint-sw01-bru01", []),
]


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, str]]]:
    """Replace the Infrahub reads and record (read, branch) calls."""
    calls: list[tuple[str, str]] = []

    def fake_run_query(name: str, variables: dict[str, Any] | None = None, branch: str = "main") -> dict[str, Any]:
        calls.append((name, branch))
        return build_q1(STATUSES_BY_BRANCH[branch])

    def fake_filter_nodes(kind: type, filters: dict[str, Any] | None = None, branch: str = "main", **_: Any) -> list:  # noqa: ANN401
        calls.append((kind.__name__, branch))
        assert filters == {"state__value": "open"}
        return PROPOSED_CHANGES

    monkeypatch.setattr(infrahub, "run_query", fake_run_query)
    monkeypatch.setattr(infrahub, "filter_nodes", fake_filter_nodes)
    st.cache_data.clear()
    yield calls
    st.cache_data.clear()


def _metrics(app: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in app.metric}


def _markdown(app: AppTest) -> list[str]:
    return [element.value for element in app.markdown]


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
    assert "## 2 Gold services for Northbank have no other path during this change" in _markdown(app)
    assert [caption.value for caption in app.main.caption] == [
        "Paris router 1 maintenance · found in a proposed change, before merge",
        "Counted",
        "Counted",
        "Your input",
    ]
    assert _metrics(app) == {
        "Customers affected": "3",
        "Gold services affected": "2 of 5",
        "Gold SLA credit exposure, per month": "€2,565",
    }
    assert [expander.label for expander in app.expander] == [
        "Affected services",
        "Edge routers ranked by Gold contract value · your input",
    ]
    assert ("business_impact_services", "maint-rb01-par01") in reads
    assert ("business_impact_services", "main") in reads


def test_page_on_current_network(reads: list[tuple[str, str]]) -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    app.sidebar.selectbox(key="business-impact-change").select_index(0).run(timeout=30)

    assert not app.exception
    assert "## No service is affected" in _markdown(app)
    assert _metrics(app) == {
        "Customers affected": "0",
        "Gold services affected": "0 of 5",
        "Gold SLA credit exposure, per month": "€0",
    }


def test_page_on_brussels_switch_1_maintenance(reads: list[tuple[str, str]]) -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    app.sidebar.selectbox(key="business-impact-change").select_index(1).run(timeout=30)

    assert not app.exception
    assert "## 1 Gold service for Helix Health has no other path during this change" in _markdown(app)
    assert _metrics(app)["Gold services affected"] == "1 of 5"
    assert _metrics(app)["Gold SLA credit exposure, per month"] == "€2,025"


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


def test_view_selector_names_both_views(reads: list[tuple[str, str]]) -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)

    assert not app.exception
    assert list(app.sidebar.radio(key="business-impact-view").options) == ["Blast radius", "Single points of failure"]
    assert app.sidebar.radio(key="business-impact-view").value == "Blast radius"


def _open_single_points(reads: list[tuple[str, str]] | None = None) -> AppTest:
    app = AppTest.from_file(PAGE).run(timeout=30)
    if reads is not None:
        reads.clear()  # Keep only the reads of the Single points of failure view.
    return app.sidebar.radio(key="business-impact-view").set_value("Single points of failure").run(timeout=30)


def test_single_points_view(reads: list[tuple[str, str]]) -> None:
    """Headline, the dependency table, and the failure of the first device in it."""
    app = _open_single_points(reads)

    assert not app.exception
    assert not app.error
    markdown = _markdown(app)
    assert "## 5 of 5 Gold services have a single point of failure" in markdown
    assert "#### If Paris edge router 1 failed now, 2 Gold services for Northbank would have no path" in markdown
    table = app.dataframe[0].value
    assert list(table["Device"])[:2] == ["Paris edge router 1", "Paris switch 1"]
    assert list(table.columns) == [
        "Device",
        "Role",
        "Gold services",
        "Customers",
        "Gold contract value per year (EUR) · your input",
        "Gold SLA credit per month (EUR) · your input",
    ]
    assert _metrics(app) == {
        "Customers affected": "3",
        "Gold services affected": "2 of 5",
        "Gold SLA credit exposure, per month": "€2,565",
    }
    # The view reads the current network only.
    assert not [branch for name, branch in reads if name == "business_impact_services" and branch != "main"]


def test_single_points_view_with_another_device(reads: list[tuple[str, str]]) -> None:
    app = _open_single_points()
    app.selectbox(key="business-impact-device").set_value("Brussels switch 1").run(timeout=30)

    assert not app.exception
    assert "#### If Brussels switch 1 failed now, 1 Gold service for Helix Health would have no path" in _markdown(app)
    assert _metrics(app)["Gold SLA credit exposure, per month"] == "€2,025"


def test_single_points_copy_never_says_branch(reads: list[tuple[str, str]]) -> None:
    app = _open_single_points()
    texts = [*_copy(app), app.selectbox(key="business-impact-device").help or ""]

    assert texts
    assert not [text for text in texts if "branch" in text.lower()]


def test_proposed_change_read_error_falls_back_to_current_network(
    reads: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed proposed change read shows a fixed message and a picker with only Current network."""

    def failing_filter_nodes(*_: object, **__: object) -> list:
        message = "proposed changes unreachable on branch main"
        raise RuntimeError(message)

    monkeypatch.setattr(infrahub, "filter_nodes", failing_filter_nodes)
    app = AppTest.from_file(PAGE).run(timeout=30)

    assert not app.exception
    assert [error.value for error in app.sidebar.error] == [
        "Could not read the proposed changes from Infrahub. The page log has the details."
    ]
    assert list(app.sidebar.selectbox(key="business-impact-change").options) == ["Current network"]
    assert "## No service is affected" in _markdown(app)
    assert not [text for text in _copy(app) if "branch" in text.lower()]


def test_current_network_shows_no_headline_caption(reads: list[tuple[str, str]]) -> None:
    app = AppTest.from_file(PAGE).run(timeout=30)
    app.sidebar.selectbox(key="business-impact-change").select_index(0).run(timeout=30)

    assert not app.exception
    assert [caption.value for caption in app.main.caption] == ["Counted", "Counted", "Your input"]


HOME = str(REPO_ROOT / "service_catalog" / "🏠_Home_Page.py")


def test_home_page_links_to_business_impact() -> None:
    app = AppTest.from_file(HOME).run(timeout=30)

    assert not app.exception
    assert "## Understand business impact" in [element.value for element in app.markdown]
    assert "📊 Business impact" in [header.value for header in app.header]
    assert "business_impact" in [button.key for button in app.button]
