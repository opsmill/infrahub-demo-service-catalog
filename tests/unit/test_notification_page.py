"""Unit tests of the Customer notification page: its grouping, its file notices and a smoke run.

The grouping and the notices live in `notification_view.py` and are tested as
plain functions. The smoke run uses Streamlit's AppTest with the Infrahub reads
replaced: the live list and the artifact content are built by `notification.py`
from the seed-shaped query fixture, as the affected customers transform builds
them.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from streamlit.testing.v1 import AppTest

from service_catalog.artifact_view import REGENERATE, REGENERATE_FAILED, STALE
from service_catalog.business_impact.gold_outage_guard import evaluate
from service_catalog.business_impact.notification import affected_customers, affected_customers_report
from service_catalog.business_impact.notification_view import (
    ARTIFACT_NAME,
    BLOCKED_CAPTION,
    GENERATION_FAILED,
    NO_CUSTOMER_AFFECTED,
    NOT_GENERATED,
    UNREADABLE,
    CustomerRow,
    Notice,
    NotificationList,
    change_options,
    file_notice,
    notification_state,
    parse_artifact,
    status_heading,
)
from service_catalog.infrahub import ARTIFACT_ERROR, ARTIFACT_READY, Generation, StoredArtifact

from .builders import (
    BRUSSELS,
    NEW_YORK,
    PARIS,
    REPO_ROOT,
    build_seeded_q1,
    proposed_change,
)

if TYPE_CHECKING:
    from collections.abc import Callable

PAGE = str(REPO_ROOT / "service_catalog" / "views" / "4_📣_Customer_Notification.py")

MAIN = build_seeded_q1()


def _artifact(branch: str, statuses: dict[str, str]) -> str:
    data = build_seeded_q1(statuses)
    result = evaluate(data, MAIN, branch)
    return json.dumps(affected_customers_report(branch, affected_customers(data, MAIN, result), result))


ARTIFACTS: dict[str, str | None] = {
    "maint-rb01-par01": _artifact("maint-rb01-par01", {"rb01-par01": "maintenance"}),
    "maint-sw01-bru01": _artifact("maint-sw01-bru01", {"sw01-bru01": "maintenance"}),
    "maint-rb01-nyc01": _artifact("maint-rb01-nyc01", {"rb01-nyc01": "maintenance"}),
    "maint-new": None,
}
# Main's copy: the list a branch shows before Infrahub generates the artifact on it.
MAIN_COPY = _artifact("main", {})

PARIS_DOWN = {"rb01-par01": "maintenance"}
# The artifact each branch holds, as the page reads it from Infrahub.
STORED: dict[str, StoredArtifact | None] = {
    **{branch: StoredArtifact(ARTIFACT_READY, content) for branch, content in ARTIFACTS.items() if content},
    "maint-new": None,
    "maint-inherited": StoredArtifact(ARTIFACT_READY, MAIN_COPY),
    "maint-processing": StoredArtifact("Processing"),
    "maint-failed": StoredArtifact(ARTIFACT_ERROR),
    "maint-broken": StoredArtifact(ARTIFACT_READY, "{not json"),
    # Generated before the change took the Paris router down, so it lists no customer.
    "maint-stale": StoredArtifact(ARTIFACT_READY, _artifact("maint-stale", {})),
}
# The list each branch has now, as the page computes it from the live data. Each branch other than the
# three seeded changes takes Paris router 1 down.
LIVE: dict[str, dict[str, Any]] = {
    branch: json.loads(ARTIFACTS.get(branch) or _artifact(branch, PARIS_DOWN)) for branch in STORED
}


# Grouping and empty states


def test_paris_groups_two_notified_customers_before_two_not_notified() -> None:
    result = parse_artifact(ARTIFACTS["maint-rb01-par01"])

    assert result is not None
    assert not result.blocked
    assert [(group.status, group.rows) for group in result.groups] == [
        (
            "at risk, notified",
            (
                CustomerRow("Helix Health", "Gold", "DI-1003"),
                CustomerRow("Northbank", "Gold", "DI-1001, DI-1002"),
            ),
        ),
        (
            "down, not notified",
            (
                CustomerRow("Maison Verte", "Silver", "DI-1004"),
                CustomerRow("Rapid Freight", "Bronze", "DI-1006"),
            ),
        ),
    ]
    assert [status_heading(group) for group in result.groups] == ["At risk, notified (2)", "Down, not notified (2)"]


def test_brussels_is_blocked_with_the_gold_customer_first() -> None:
    result = parse_artifact(ARTIFACTS["maint-sw01-bru01"])

    assert result is not None
    assert result.blocked
    assert [group.status for group in result.groups] == ["down, change blocked", "down, not notified"]


def test_an_empty_list_is_not_a_missing_list() -> None:
    result = parse_artifact(ARTIFACTS["maint-rb01-nyc01"])

    assert result is not None
    assert result.groups == ()


@pytest.mark.parametrize("content", [None, "", "not json", "[]", '{"branch": "main"}'])
def test_parse_artifact_reads_no_list_from_unreadable_content(content: str | None) -> None:
    assert parse_artifact(content) is None


def test_a_ready_list_of_the_selected_change_is_shown() -> None:
    state = notification_state(ARTIFACTS["maint-rb01-par01"], "maint-rb01-par01")

    assert isinstance(state, NotificationList)
    assert [group.status for group in state.groups] == ["at risk, notified", "down, not notified"]


@pytest.mark.parametrize(
    ("content", "branch"),
    [
        pytest.param(None, "maint-new", id="no artifact or not Ready"),
        pytest.param(MAIN_COPY, "maint-inherited", id="main's copy"),
        pytest.param(ARTIFACTS["maint-rb01-par01"], "maint-sw01-bru01", id="another change's list"),
    ],
)
def test_a_list_not_generated_for_the_selected_change_is_not_generated_yet(content: str | None, branch: str) -> None:
    assert notification_state(content, branch) == Notice(NOT_GENERATED)


def test_a_failed_generation_is_an_error() -> None:
    assert notification_state(None, "maint-failed", failed=True) == Notice(GENERATION_FAILED, error=True)


@pytest.mark.parametrize("content", ["{not json", "[]", '{"branch": "maint-broken"}'])
def test_unreadable_content_is_an_error_not_a_missing_list(content: str) -> None:
    assert notification_state(content, "maint-broken") == Notice(UNREADABLE, error=True)


def test_a_stored_list_equal_to_the_live_list_needs_no_notice() -> None:
    branch = "maint-rb01-par01"

    assert file_notice(ARTIFACTS[branch], LIVE[branch], branch) is None


def test_a_stored_list_other_than_the_live_list_is_older() -> None:
    stored = STORED["maint-stale"]

    assert stored is not None
    assert file_notice(stored.content, LIVE["maint-stale"], "maint-stale") == Notice(STALE, warning=True)


@pytest.mark.parametrize(
    ("branch", "notice"),
    [
        ("maint-new", Notice(NOT_GENERATED)),
        ("maint-inherited", Notice(NOT_GENERATED)),
        ("maint-failed", Notice(GENERATION_FAILED, error=True)),
        ("maint-broken", Notice(UNREADABLE, error=True)),
    ],
)
def test_a_missing_failed_or_unreadable_file_has_its_notice(branch: str, notice: Notice) -> None:
    stored = STORED[branch]
    content = stored.content if stored else None
    failed = stored is not None and stored.failed

    assert file_notice(content, LIVE[branch], branch, failed=failed) == notice


def test_change_options_leave_out_the_current_network_and_service_orders() -> None:
    changes = [
        {"name": "Paris router 1 maintenance", "source_branch": "maint-rb01-par01", "tags": []},
        {"name": "Implement service di-3001", "source_branch": "implement_di-3001", "tags": ["service_request"]},
        {"name": "Brussels switch 1 maintenance", "source_branch": "maint-sw01-bru01", "tags": []},
        {"name": "Merged change", "source_branch": "old", "state": "merged", "tags": []},
    ]

    assert [(entry.label, entry.branch) for entry in change_options(changes)] == [
        ("Brussels switch 1 maintenance", "maint-sw01-bru01"),
        ("Paris router 1 maintenance", "maint-rb01-par01"),
    ]


# Smoke run of the page


PROPOSED_CHANGES = [
    proposed_change(PARIS, "maint-rb01-par01"),
    proposed_change(BRUSSELS, "maint-sw01-bru01"),
    proposed_change(NEW_YORK, "maint-rb01-nyc01"),
    proposed_change("A new change", "maint-new"),
    proposed_change("Change with main's copy", "maint-inherited"),
    proposed_change("Change still processing", "maint-processing"),
    proposed_change("Change that failed", "maint-failed"),
    proposed_change("Change with a broken list", "maint-broken"),
    proposed_change("Change with an older list", "maint-stale"),
]


@pytest.fixture
def reads(replace_reads: Callable[..., None]) -> list[tuple[str, str]]:
    """Replace the Infrahub reads and the generation request, and record (call, branch) calls.

    The generation request answers with `outcome`, which a test can replace in `GENERATION`.
    """
    calls: list[tuple[str, str]] = []
    GENERATION["outcome"] = Generation.READY

    def fake_run_async(read: Callable[..., Any], branch: str) -> dict[str, Any]:
        calls.append((read.__name__, branch))
        return LIVE[branch]

    def fake_generate_artifact(artifact_name: str, branch: str = "main", **_: Any) -> Generation:  # noqa: ANN401
        calls.append((f"generate {artifact_name}", branch))
        return GENERATION["outcome"]

    def fake_read_stored_artifact(artifact_name: str, branch: str = "main", **_: Any) -> StoredArtifact | None:  # noqa: ANN401
        calls.append((artifact_name, branch))
        return STORED[branch]

    def fake_filter_nodes(kind: type, filters: dict[str, Any] | None = None, branch: str = "main", **_: Any) -> list:  # noqa: ANN401
        calls.append((kind.__name__, branch))
        return PROPOSED_CHANGES

    replace_reads(
        read_stored_artifact=fake_read_stored_artifact,
        filter_nodes=fake_filter_nodes,
        run_async=fake_run_async,
        generate_artifact=fake_generate_artifact,
    )
    return calls


GENERATION: dict[str, Generation] = {}


def _select(change: str) -> AppTest:
    app = AppTest.from_file(PAGE).run(timeout=30)
    app.sidebar.selectbox(key="customer-notification-change").select(change).run(timeout=30)
    assert not app.exception
    return app


def test_page_shows_the_paris_list_grouped_by_status(reads: list[tuple[str, str]]) -> None:
    app = _select("Paris router 1 maintenance")

    # Each status group is open when the page loads.
    assert [(expander.label, expander.proto.expanded) for expander in app.expander] == [
        ("At risk, notified (2)", True),
        ("Down, not notified (2)", True),
    ]
    tables = [frame.value.to_dict("records") for frame in app.dataframe]
    assert tables == [
        [
            {"Customer": "Helix Health", "Tier": "Gold", "Services": "DI-1003"},
            {"Customer": "Northbank", "Tier": "Gold", "Services": "DI-1001, DI-1002"},
        ],
        [
            {"Customer": "Maison Verte", "Tier": "Silver", "Services": "DI-1004"},
            {"Customer": "Rapid Freight", "Tier": "Bronze", "Services": "DI-1006"},
        ],
    ]
    assert ("read_affected_report", "maint-rb01-par01") in reads
    assert (ARTIFACT_NAME, "maint-rb01-par01") in reads
    # The stored list is the live list, so the page says nothing about the file.
    assert not app.warning
    assert not app.info
    assert not app.button


def test_page_says_a_blocked_change_notifies_no_one(reads: list[tuple[str, str]]) -> None:
    app = _select("Brussels switch 1 maintenance")

    assert BLOCKED_CAPTION in [caption.value for caption in app.main.caption]


def test_page_says_when_no_customer_is_affected(reads: list[tuple[str, str]]) -> None:
    app = _select("New York router 1 maintenance")

    assert NO_CUSTOMER_AFFECTED in [element.value for element in app.markdown]
    assert not app.dataframe


@pytest.mark.parametrize("change", ["A new change", "Change with main's copy", "Change still processing"])
def test_page_says_when_the_file_is_not_generated_yet(reads: list[tuple[str, str]], change: str) -> None:
    app = _select(change)

    assert [info.value for info in app.info] == [NOT_GENERATED]
    assert not app.error
    assert [button.label for button in app.button] == [REGENERATE]
    # The list itself comes from the live data.
    assert [expander.label for expander in app.expander] == ["At risk, notified (2)", "Down, not notified (2)"]


@pytest.mark.parametrize(
    ("change", "message"),
    [("Change that failed", GENERATION_FAILED), ("Change with a broken list", UNREADABLE)],
)
def test_page_shows_an_error_for_a_failed_or_unreadable_file(
    reads: list[tuple[str, str]], change: str, message: str
) -> None:
    app = _select(change)

    assert [error.value for error in app.error] == [message]
    assert not app.info
    assert [button.label for button in app.button] == [REGENERATE]
    assert app.dataframe


def test_page_says_when_the_file_is_older_than_the_list(reads: list[tuple[str, str]]) -> None:
    app = _select("Change with an older list")

    assert [warning.value for warning in app.warning] == [STALE]
    assert [expander.label for expander in app.expander] == ["At risk, notified (2)", "Down, not notified (2)"]


def test_regenerate_asks_infrahub_for_the_file_of_the_selected_change(reads: list[tuple[str, str]]) -> None:
    app = _select("Change with an older list")
    app.button(key="customer-notification-regenerate").click().run(timeout=30)

    assert not app.exception
    assert (f"generate {ARTIFACT_NAME}", "maint-stale") in reads


def test_regenerate_says_when_infrahub_could_not_generate_the_file(reads: list[tuple[str, str]]) -> None:
    GENERATION["outcome"] = Generation.FAILED
    app = _select("Change with an older list")
    app.button(key="customer-notification-regenerate").click().run(timeout=30)

    assert [error.value for error in app.error] == [REGENERATE_FAILED]


def test_page_shows_no_cost_maintenance_planning_or_sla(reads: list[tuple[str, str]]) -> None:
    app = _select("Paris router 1 maintenance")
    texts = [element.value for element in (*app.markdown, *app.caption, *app.info, *app.warning)]
    texts += [str(frame.value.to_dict("records")) for frame in app.dataframe]
    texts += [expander.label for expander in app.expander]

    words = ("cost", "eur", "€", "sla", "credit", "price", "path", "maintenance window", "single point")
    on_screen = " ".join(texts).lower().replace("maintenance", "")
    assert not [word for word in words if word in on_screen]
