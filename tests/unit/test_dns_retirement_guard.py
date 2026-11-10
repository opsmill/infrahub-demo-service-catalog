"""Unit tests for the DNS retirement guard.

Runs `evaluate` on query results shaped like `checks/dns_retirement_guard.gql`, with the records,
applications and teams of `data/dns/dns.yml`. Then runs the check with a fake client, for the
read failures, and imports the check file the way the Infrahub task worker does, from a commit
worktree, to prove that it reads the DNS query next to itself.
"""

from __future__ import annotations

import asyncio
import importlib
import shutil
from typing import TYPE_CHECKING, Any, cast

import pytest
import yaml

from checks.dns_retirement_guard import (
    ACTIVE,
    DISBANDED,
    MESSAGE_WIDTH,
    DnsRetirementGuard,
    evaluate,
    lines,
)
from infrahub_sdk.exceptions import Error as SdkError
from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError, ServerNotReachableError

from .builders import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    from infrahub_sdk import InfrahubClient

BRANCH = "retire-portal"
ZONE = "example.net"

WEB_PLATFORM = {"name": "Web Platform", "email": "web-platform@example.net", "status": "active"}
BILLING_SYSTEMS = {"name": "Billing Systems", "email": "billing-systems@example.net", "status": "disbanded"}
IDENTITY = {"name": "Identity", "email": "identity@example.net", "status": "active"}

PORTAL_MESSAGE = (
    "portal.example.net (A) is marked for retirement but still serves 1 active application: "
    "Customer portal (owned by Web Platform, web-platform@example.net). "
    "Move the application off this record before you retire it."
)
OLD_FTP_WARNING = (
    "old-ftp.example.net (A) is marked for retirement and has no application in Infrahub. "
    "Nothing in Infrahub shows that it is unused, so confirm with the zone owner before you merge."
)
WWW_WARNING = (
    "www.example.net (CNAME) points at portal.example.net, which this change marks for retirement. "
    "The CNAME stops resolving when the record is retired, so retire or repoint it too."
)
PORTAL_ON_MAIN_WARNING = (
    "portal.example.net (A) is already marked for retirement on main but still serves 1 active application: "
    "Customer portal (owned by Web Platform, web-platform@example.net). This change does not cause it."
)
READ_FAILURE = "DNS retirement guard could not read the DNS records"


def app(name: str, status: str = "active", owner: dict[str, str] | None = None) -> dict[str, Any]:
    """One application edge of a record, with its owning team when it has one."""
    team = None
    if owner is not None:
        team = {
            "name": {"value": owner["name"]},
            "contact_email": {"value": owner["email"]},
            "status": {"value": owner["status"]},
        }
    return {"node": {"name": {"value": name}, "status": {"value": status}, "owner": {"node": team}}}


def record(name: str, record_type: str = "A", applications: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One record edge of the `retiring` block."""
    return {
        "node": {
            "display_label": f"{name}.{ZONE} {record_type}",
            "name": {"value": name},
            "record_type": {"value": record_type},
            "zone": {"node": {"name": {"value": ZONE}}},
            "applications": {"edges": applications or []},
        }
    }


def cname(name: str, value: str) -> dict[str, Any]:
    """One record edge of the `cnames` block."""
    return {"node": {"display_label": f"{name}.{ZONE} CNAME", "value": {"value": value}}}


def result(retiring: list[dict[str, Any]], cnames: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The DNS query result of one branch."""
    return {"cnames": {"edges": cnames or []}, "retiring": {"edges": retiring}}


def portal() -> dict[str, Any]:
    return record("portal", applications=[app("Customer portal", owner=WEB_PLATFORM)])


# The rule


def test_active_application_with_an_active_team_fails_and_names_the_team_and_its_email() -> None:
    guard = evaluate(result([portal()]), {})

    assert guard.errors == [PORTAL_MESSAGE]
    assert guard.warnings == []


def test_active_application_with_a_disbanded_team_says_nobody_owns_it() -> None:
    invoices = record("invoices", applications=[app("Invoice archive", owner=BILLING_SYSTEMS)])

    guard = evaluate(result([invoices]), {})

    assert guard.errors == [
        "invoices.example.net (A) is marked for retirement but still serves 1 active application: "
        "Invoice archive (owned by Billing Systems, which is disbanded, so nobody owns it today). "
        "Move the application off this record before you retire it."
    ]


def test_active_application_with_no_owning_team() -> None:
    reports = record("reports", applications=[app("Report viewer")])

    guard = evaluate(result([reports]), {})

    assert guard.errors == [
        "reports.example.net (A) is marked for retirement but still serves 1 active application: "
        "Report viewer (with no owning team). Move the application off this record before you retire it."
    ]


def test_only_retired_applications_give_no_message() -> None:
    intranet = record("intranet", applications=[app("Legacy intranet", "retired", WEB_PLATFORM)])

    guard = evaluate(result([intranet]), {})

    assert guard.errors == []
    assert guard.warnings == []


def test_no_application_gives_one_warning_and_no_error() -> None:
    guard = evaluate(result([record("old-ftp")]), {})

    assert guard.errors == []
    assert guard.warnings == [OLD_FTP_WARNING]


def test_one_active_and_one_retired_application_names_only_the_active_one() -> None:
    mail = record(
        "mail",
        applications=[app("Single sign-on", owner=IDENTITY), app("Legacy intranet", "retired", WEB_PLATFORM)],
    )

    guard = evaluate(result([mail]), {})

    assert guard.errors == [
        "mail.example.net (A) is marked for retirement but still serves 1 active application: "
        "Single sign-on (owned by Identity, identity@example.net). "
        "Move the application off this record before you retire it."
    ]
    assert "Legacy intranet" not in guard.errors[0]


def test_two_active_applications_are_counted_and_named_in_name_order() -> None:
    shared = record(
        "shared",
        applications=[app("Single sign-on", owner=IDENTITY), app("Customer portal", owner=WEB_PLATFORM)],
    )

    guard = evaluate(result([shared]), {})

    assert guard.errors == [
        "shared.example.net (A) is marked for retirement but still serves 2 active applications: "
        "Customer portal (owned by Web Platform, web-platform@example.net); "
        "Single sign-on (owned by Identity, identity@example.net). "
        "Move the applications off this record before you retire it."
    ]


def test_no_record_marked_for_retirement_gives_nothing() -> None:
    assert evaluate(result([]), {}) == evaluate({}, {})
    guard = evaluate(result([]), {})
    assert guard.errors == []
    assert guard.warnings == []


def test_record_already_marked_on_main_gives_only_an_information_message() -> None:
    """A record retiring on main is not caused by this change, so it does not block it."""
    guard = evaluate(result([portal()]), result([portal()]))

    assert guard.errors == []
    assert guard.warnings == [PORTAL_ON_MAIN_WARNING]


def test_record_already_marked_on_main_with_no_active_application_gives_nothing() -> None:
    guard = evaluate(result([record("old-ftp")]), result([record("old-ftp")]))

    assert guard.errors == []
    assert guard.warnings == []


def test_only_the_newly_marked_record_fails_next_to_one_already_marked_on_main() -> None:
    invoices = record("invoices", applications=[app("Invoice archive", owner=BILLING_SYSTEMS)])

    guard = evaluate(result([portal(), invoices]), result([portal()]))

    assert len(guard.errors) == 1
    assert guard.errors[0].startswith("invoices.example.net (A) is marked for retirement")
    assert guard.warnings == [PORTAL_ON_MAIN_WARNING]


def test_active_cname_that_points_at_a_newly_marked_record_gives_a_warning() -> None:
    guard = evaluate(result([portal()], [cname("www", "portal.example.net.")]), {})

    assert guard.errors == [PORTAL_MESSAGE]
    assert guard.warnings == [WWW_WARNING]


def test_active_cname_that_points_at_another_record_gives_no_warning() -> None:
    guard = evaluate(result([portal()], [cname("docs", "sso.example.net.")]), {})

    assert guard.errors == [PORTAL_MESSAGE]
    assert guard.warnings == []


def test_cname_warning_is_given_once_when_the_a_and_aaaa_records_are_both_marked() -> None:
    portal_aaaa = record("portal", "AAAA", [app("Customer portal", owner=WEB_PLATFORM)])

    guard = evaluate(result([portal(), portal_aaaa], [cname("www", "portal.example.net.")]), {})

    assert len(guard.errors) == 2
    assert guard.warnings == [WWW_WARNING]


def test_cname_of_a_record_already_marked_on_main_gives_no_cname_warning() -> None:
    guard = evaluate(result([portal()], [cname("www", "portal.example.net.")]), result([portal()]))

    assert guard.warnings == [PORTAL_ON_MAIN_WARNING]


def test_messages_are_sorted_by_record_display_label() -> None:
    sso = record("sso", applications=[app("Single sign-on", owner=IDENTITY)])
    invoices = record("invoices", applications=[app("Invoice archive", owner=BILLING_SYSTEMS)])

    guard = evaluate(result([sso, portal(), invoices]), {})

    assert [message.split(" ", 1)[0] for message in guard.errors] == [
        "invoices.example.net",
        "portal.example.net",
        "sso.example.net",
    ]


def test_every_message_fits_the_infrahub_message_box() -> None:
    invoices = record("invoices", applications=[app("Invoice archive", owner=BILLING_SYSTEMS)])
    guard = evaluate(
        result([portal(), invoices, record("old-ftp")], [cname("www", "portal.example.net.")]),
        result([record("sso", applications=[app("Single sign-on", owner=IDENTITY)])]),
    )
    messages = [*guard.errors, *guard.warnings]

    assert len(messages) == 4
    for message in messages:
        wrapped = lines(message)
        assert len(wrapped.splitlines()) > 1
        assert all(len(line) <= MESSAGE_WIDTH for line in wrapped.splitlines())
        assert wrapped.replace("\n", " ") == message


# The check with a fake client


class FakeClient:
    """Stand-in for the SDK client: the schema and the DNS query by branch.

    `results` maps a branch to its DNS query result, or to the error the read raises. A branch
    missing from `results` has no DNS schema. `schema_error`, when set, is what the schema lookup
    raises on every branch.
    """

    def __init__(self, results: dict[str, dict[str, Any] | Exception], schema_error: SdkError | None = None) -> None:
        self.results = results
        self.schema_error = schema_error
        self.schema = self
        self.reads: list[str] = []

    async def get(self, kind: str, branch: str) -> object:
        if self.schema_error is not None:
            raise self.schema_error
        if branch not in self.results:
            raise SchemaNotFoundError(identifier=kind)
        return object()

    async def execute_graphql(self, query: str, branch_name: str, **_: object) -> dict[str, Any]:
        assert "DnsRetirementRecords" in query
        self.reads.append(branch_name)
        answer = self.results[branch_name]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _run(client: FakeClient, branch: str = BRANCH) -> DnsRetirementGuard:
    check = DnsRetirementGuard(branch=branch, client=cast("InfrahubClient", client))
    asyncio.run(check.run())
    return check


def _messages(check: DnsRetirementGuard, level: str) -> list[str]:
    """The messages the check logged at `level`, with their line breaks turned back into spaces."""
    return [str(log["message"]).replace("\n", " ") for log in check.logs if log["level"] == level]


def _own_messages(check: DnsRetirementGuard) -> list[str]:
    """Every message except the SDK's own line on a passing check."""
    return [str(log["message"]) for log in check.logs if log["message"] != "Check succesfully completed"]


def test_check_fails_on_the_portal_record_and_reads_the_branch_then_main() -> None:
    client = FakeClient({BRANCH: result([portal()]), "main": result([])})

    check = _run(client)

    assert not check.passed
    assert _messages(check, "ERROR") == [PORTAL_MESSAGE]
    assert client.reads == [BRANCH, "main"]


def test_check_wraps_each_message_at_the_message_width() -> None:
    client = FakeClient({BRANCH: result([portal(), record("old-ftp")]), "main": result([])})

    check = _run(client)

    message_lines = [line for message in _own_messages(check) for line in message.splitlines()]
    assert len(message_lines) > 2
    assert all(len(line) <= MESSAGE_WIDTH for line in message_lines)


def test_check_logs_warnings_as_information_and_passes() -> None:
    client = FakeClient({BRANCH: result([record("old-ftp")]), "main": result([])})

    check = _run(client)

    assert check.passed
    assert _messages(check, "ERROR") == []
    assert OLD_FTP_WARNING in _messages(check, "INFO")


def test_check_passes_on_the_intranet_record() -> None:
    intranet = record("intranet", applications=[app("Legacy intranet", "retired", WEB_PLATFORM)])

    check = _run(FakeClient({BRANCH: result([intranet]), "main": result([])}))

    assert check.passed
    assert _own_messages(check) == []


def test_branch_without_the_dns_schema_passes_with_no_message_and_does_not_read_main() -> None:
    client = FakeClient({"main": result([portal()])})

    check = _run(client)

    assert check.passed
    assert _own_messages(check) == []
    assert client.reads == []


def test_main_without_the_dns_schema_counts_as_no_record_marked() -> None:
    client = FakeClient({BRANCH: result([portal()])})

    check = _run(client)

    assert not check.passed
    assert _messages(check, "ERROR") == [PORTAL_MESSAGE]
    assert client.reads == [BRANCH]


@pytest.mark.parametrize("failing", [BRANCH, "main"])
def test_check_fails_when_the_dns_query_is_refused(failing: str) -> None:
    """A query that cannot run must not read as "no record marked for retirement"."""
    results: dict[str, dict[str, Any] | Exception] = {BRANCH: result([]), "main": result([])}
    results[failing] = GraphQLError(errors=[{"message": "Unknown argument 'status__value'"}], query="query")

    check = _run(FakeClient(results))

    assert not check.passed
    assert _messages(check, "ERROR") == [f"{READ_FAILURE}: Unknown argument 'status__value'"]


def test_check_fails_on_another_sdk_error() -> None:
    results: dict[str, dict[str, Any] | Exception] = {
        BRANCH: ServerNotReachableError(address="http://infrahub-server:8000"),
        "main": result([]),
    }

    check = _run(FakeClient(results))

    assert not check.passed
    errors = _messages(check, "ERROR")
    assert len(errors) == 1
    assert errors[0].startswith(f"{READ_FAILURE}: ")
    assert "infrahub-server" in errors[0]


def test_check_fails_when_the_schema_lookup_raises_another_sdk_error() -> None:
    """Only SchemaNotFoundError means "no DNS schema". Any other error of the lookup is a failed read."""
    client = FakeClient(
        {BRANCH: result([]), "main": result([])},
        schema_error=ServerNotReachableError(address="http://infrahub-server:8000"),
    )

    check = _run(client)

    assert not check.passed
    errors = _messages(check, "ERROR")
    assert len(errors) == 1
    assert errors[0].startswith(f"{READ_FAILURE}: ")
    assert "infrahub-server" in errors[0]
    assert client.reads == []


def test_check_fails_when_a_record_has_no_zone_name() -> None:
    """A missing zone name must not turn into a record named `portal.None`."""
    broken = portal()
    broken["node"]["zone"] = {"node": {"name": {"value": None}}}

    check = _run(FakeClient({BRANCH: result([broken]), "main": result([])}))

    assert not check.passed
    errors = _messages(check, "ERROR")
    assert len(errors) == 1
    assert errors[0].startswith(f"{READ_FAILURE}: ")
    assert "portal.example.net A" in errors[0]
    assert "name" in errors[0]


@pytest.mark.parametrize("side", [BRANCH, "main"])
def test_check_fails_when_the_retiring_block_is_null(side: str) -> None:
    """`retiring: null` must not read as "no record marked for retirement"."""
    results: dict[str, dict[str, Any] | Exception] = {BRANCH: result([portal()]), "main": result([])}
    results[side] = {"cnames": {"edges": []}, "retiring": None}

    check = _run(FakeClient(results))

    assert not check.passed
    assert _messages(check, "ERROR") == [f"{READ_FAILURE}: retiring is missing"]


def test_status_values_the_check_compares_are_choices_of_the_dns_schema() -> None:
    """The check compares statuses with `active`, `disbanded` and, in its query, `retiring`. Each must
    be a dropdown choice of the attribute it is compared with, or the comparison never matches.
    """
    schema = yaml.safe_load((REPO_ROOT / "schemas" / "dns" / "dns.yml").read_text(encoding="utf-8"))
    nodes = {f"{node['namespace']}{node['name']}": node for node in schema["nodes"]}

    def choices(kind: str) -> set[str]:
        (status,) = [attribute for attribute in nodes[kind]["attributes"] if attribute["name"] == "status"]
        assert status["kind"] == "Dropdown"
        return {choice["name"] for choice in status["choices"]}

    query = (REPO_ROOT / "checks" / "dns_retirement_guard.gql").read_text(encoding="utf-8")
    assert 'status__value: "retiring"' in query
    assert 'status__value: "active"' in query
    assert {ACTIVE, "retiring"} <= choices("DnsRecord")
    assert {ACTIVE, "retired"} <= choices("DnsApplication")
    assert {ACTIVE, DISBANDED} <= choices("DnsTeam")


def test_worker_imports_the_check_and_reads_the_query_from_the_commit_worktree(commit_worktree: Path) -> None:
    """Infrahub imports `commits.<sha>.checks.dns_retirement_guard` with only the repository directory on
    sys.path, so the check must read the DNS query next to itself in the same worktree.
    """
    worktree = commit_worktree
    (worktree / "checks").mkdir()
    for name in ("__init__.py", "dns_retirement_guard.py", "dns_retirement_guard.gql"):
        shutil.copy(REPO_ROOT / "checks" / name, worktree / "checks" / name)
    module = importlib.import_module(f"commits.{worktree.name}.checks.dns_retirement_guard")

    assert str(module.__file__).startswith(str(worktree))
    assert worktree / "checks" / "dns_retirement_guard.gql" == module.QUERY_FILE
    assert "DnsRetirementRecords" in module.dns_query()

    client = FakeClient({BRANCH: result([portal()]), "main": result([])})
    check = module.DnsRetirementGuard(branch=BRANCH, client=client)
    asyncio.run(check.run())
    assert not check.passed
    assert client.reads == [BRANCH, "main"]
