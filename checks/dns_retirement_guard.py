"""DNS retirement guard: fails a proposed change that marks for retirement a DNS record an active application uses.

Registered under `check_definitions` in `.infrahub.yml` with no `targets`, so it runs once in
every proposed change pipeline.

The DNS schema is optional: `invoke seed-dns` loads `schemas/dns`, and the repository import does
not. Infrahub refuses a stored query that names a kind the schema does not have, so the DNS read,
`dns_retirement_guard.gql` next to this file, is not a stored query. The class binds the stored
query `dns_retirement_guard` (`dns_retirement_guard_binding.gql`, which reads only the Infrahub
version) because Infrahub requires each check to bind one, and it overrides `collect_data`:

1. When the branch's schema has no `DnsRecord`, the check passes with no message and reads nothing.
2. Otherwise it runs the DNS read on the branch and on main. Main counts as having no record marked
   for retirement when its schema has no `DnsRecord`.
3. Any other read error fails the check, so a read it could not make never passes.

Then it applies the rule (`evaluate`): only records that this change marks for retirement (retiring
on the branch and not on main) can fail it. The rule lives in this file and imports nothing from
`service_catalog`, because Infrahub imports a check file as `commits.<sha>.checks.<name>` with only
the repository directory on `sys.path`. The DNS read is found relative to this file, so the check
always reads the query of the commit it came from.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from infrahub_sdk.checks import InfrahubCheck
from infrahub_sdk.exceptions import Error as SdkError
from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError

if TYPE_CHECKING:
    from collections.abc import Mapping

QUERY_FILE = Path(__file__).resolve().parent / "dns_retirement_guard.gql"
RECORD_KIND = "DnsRecord"
MAIN_BRANCH = "main"
ACTIVE = "active"
DISBANDED = "disbanded"
READ_FAILURE = "DNS retirement guard could not read the DNS records"

# Infrahub shows a check message in a box that does not wrap lines, about 80 characters wide next to its
# "Message: " label, so the check breaks each message into lines of at most this width.
MESSAGE_WIDTH = 72


def lines(message: str) -> str:
    """The message on lines of at most MESSAGE_WIDTH characters, broken at spaces only, so names stay whole."""
    return textwrap.fill(message, width=MESSAGE_WIDTH, break_long_words=False, break_on_hyphens=False)


def dns_query() -> str:
    """The text of the DNS read, from this file's directory."""
    return QUERY_FILE.read_text(encoding="utf-8")


@dataclass(frozen=True)
class Team:
    name: str
    contact_email: str | None
    status: str | None


@dataclass(frozen=True)
class Application:
    name: str
    status: str | None
    owner: Team | None


@dataclass(frozen=True)
class RetiringRecord:
    display_label: str
    name: str
    record_type: str
    zone: str
    applications: tuple[Application, ...]

    @property
    def fqdn(self) -> str:
        return f"{self.name}.{self.zone}"

    @property
    def title(self) -> str:
        """The record as messages name it: `portal.example.net (A)`."""
        return f"{self.fqdn} ({self.record_type})"

    @property
    def active_applications(self) -> list[Application]:
        return sorted((item for item in self.applications if item.status == ACTIVE), key=lambda item: item.name)


@dataclass(frozen=True)
class Cname:
    display_label: str
    value: str

    @property
    def title(self) -> str:
        """`www.example.net (CNAME)` from the display label `www.example.net CNAME`."""
        fqdn, _, record_type = self.display_label.rpartition(" ")
        return f"{fqdn} ({record_type})" if fqdn else self.display_label

    @property
    def target(self) -> str:
        """The name the CNAME points at, without the final dot, in lower case."""
        return self.value.rstrip(".").lower()


@dataclass(frozen=True)
class GuardResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _value(node: Mapping[str, Any] | None, name: str) -> Any:  # noqa: ANN401 - a GraphQL attribute value
    """The `value` of attribute `name` of a node, or None when the node or attribute is missing."""
    return ((node or {}).get(name) or {}).get("value")


def _peer(node: Mapping[str, Any] | None, name: str) -> Mapping[str, Any] | None:
    """The peer node of relationship `name`, or None."""
    peer: Mapping[str, Any] | None = ((node or {}).get(name) or {}).get("node")
    return peer


def _edges(block: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """The nodes of a block of edges."""
    return [edge["node"] for edge in (block or {}).get("edges") or [] if edge.get("node")]


def _team(node: Mapping[str, Any] | None) -> Team | None:
    if not node:
        return None
    return Team(
        name=str(_value(node, "name")),
        contact_email=_value(node, "contact_email"),
        status=_value(node, "status"),
    )


def parse_retiring(data: Mapping[str, Any]) -> list[RetiringRecord]:
    """The records marked for retirement in one DNS read."""
    records = []
    for node in _edges(data.get("retiring")):
        applications = tuple(
            Application(
                name=str(_value(item, "name")), status=_value(item, "status"), owner=_team(_peer(item, "owner"))
            )
            for item in _edges(node.get("applications"))
        )
        records.append(
            RetiringRecord(
                display_label=str(node["display_label"]),
                name=str(_value(node, "name")),
                record_type=str(_value(node, "record_type")),
                zone=str(_value(_peer(node, "zone"), "name")),
                applications=applications,
            )
        )
    return records


def parse_cnames(data: Mapping[str, Any]) -> list[Cname]:
    """The active CNAME records in one DNS read."""
    return [
        Cname(display_label=str(node["display_label"]), value=str(_value(node, "value") or ""))
        for node in _edges(data.get("cnames"))
    ]


def _owner(application: Application) -> str:
    """The team part of an application: who owns it and how to reach them."""
    team = application.owner
    if team is None:
        return "with no owning team"
    if team.status == DISBANDED:
        return f"owned by {team.name}, which is disbanded, so nobody owns it today"
    if team.contact_email:
        return f"owned by {team.name}, {team.contact_email}"
    return f"owned by {team.name}"


def _served(applications: list[Application]) -> str:
    """`1 active application: A (...)` or `2 active applications: A (...); B (...)`."""
    noun = "application" if len(applications) == 1 else "applications"
    names = "; ".join(f"{item.name} ({_owner(item)})" for item in applications)
    return f"{len(applications)} active {noun}: {names}"


def _failure(record: RetiringRecord) -> str:
    active = record.active_applications
    noun = "application" if len(active) == 1 else "applications"
    return (
        f"{record.title} is marked for retirement but still serves {_served(active)}. "
        f"Move the {noun} off this record before you retire it."
    )


def _no_application(record: RetiringRecord) -> str:
    return (
        f"{record.title} is marked for retirement and has no application in Infrahub. "
        "Nothing in Infrahub shows that it is unused, so confirm with the zone owner before you merge."
    )


def _cname_warning(cname: Cname, record: RetiringRecord) -> str:
    return (
        f"{cname.title} points at {record.fqdn}, which this change marks for retirement. "
        "The CNAME stops resolving when the record is retired, so retire or repoint it too."
    )


def _already_marked(record: RetiringRecord) -> str:
    return (
        f"{record.title} is already marked for retirement on main but still serves "
        f"{_served(record.active_applications)}. This change does not cause it."
    )


def evaluate(branch: Mapping[str, Any], main: Mapping[str, Any]) -> GuardResult:
    """Apply the rule to the DNS read of the branch and of main (`{}` when a side has no DNS schema).

    - A record this change marks for retirement that an active application uses: one error.
    - A record this change marks for retirement with no application: one warning.
    - An active CNAME on the branch that points at a record this change marks for retirement: one warning.
    - A record already marked for retirement on main that an active application uses: one warning.

    Messages are sorted by the display label of the record they are about.
    """
    on_main = {record.display_label for record in parse_retiring(main)}
    retiring = sorted(parse_retiring(branch), key=lambda record: record.display_label)
    cnames = sorted(parse_cnames(branch), key=lambda cname: cname.display_label)

    errors: list[str] = []
    warnings: list[str] = []
    for record in retiring:
        if record.display_label in on_main:
            if record.active_applications:
                warnings.append(_already_marked(record))
            continue
        if record.active_applications:
            errors.append(_failure(record))
        elif not record.applications:
            warnings.append(_no_application(record))
        for cname in cnames:
            message = _cname_warning(cname, record)
            # The A and the AAAA record of one name give the same CNAME warning, once.
            if cname.target == record.fqdn.lower() and message not in warnings:
                warnings.append(message)
    return GuardResult(errors=errors, warnings=warnings)


def _error_text(exc: SdkError) -> str:
    """The server's error messages for a refused query, or the SDK error's own message."""
    if isinstance(exc, GraphQLError) and exc.errors:
        return "; ".join(str(error.get("message", error)) for error in exc.errors)
    return str(exc)


class DnsRetirementGuard(InfrahubCheck):
    query = "dns_retirement_guard"
    # The error of a DNS read that failed, kept by `collect_data` for `validate`.
    _read_error: str | None = None

    async def _has_dns(self, branch: str) -> bool:
        try:
            await self.client.schema.get(kind=RECORD_KIND, branch=branch)
        except SchemaNotFoundError:
            return False
        return True

    async def _read(self, branch: str) -> dict[str, Any]:
        data: dict[str, Any] = await self.client.execute_graphql(query=dns_query(), branch_name=branch)
        return data

    async def collect_data(self) -> dict:
        """The DNS read of the branch and of main, or `{}` when the branch has no DNS schema or a read failed."""
        self._read_error = None
        try:
            if not await self._has_dns(self.branch_name):
                return {}
            branch = await self._read(self.branch_name)
            main = await self._read(MAIN_BRANCH) if await self._has_dns(MAIN_BRANCH) else {}
        except SdkError as exc:
            self._read_error = _error_text(exc)
            return {}
        return {"branch": branch, "main": main}

    def validate(self, data: dict) -> None:
        if self._read_error is not None:
            self.log_error(message=lines(f"{READ_FAILURE}: {self._read_error}"))
            return
        if not data:
            return
        result = evaluate(data["branch"], data["main"])
        for message in result.errors:
            self.log_error(message=lines(message))
        for message in result.warnings:
            self.log_info(message=lines(message))
